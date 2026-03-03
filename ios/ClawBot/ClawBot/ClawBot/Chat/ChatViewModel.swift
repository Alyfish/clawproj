import Foundation
import Combine

// MARK: - ChatViewModel

@MainActor
final class ChatViewModel: ObservableObject {

    // MARK: Published state

    @Published var messages: [ChatMessage] = []
    @Published var thinkingSteps: [ThinkingStep] = []
    @Published var isStreaming = false
    @Published var connectionState: ConnectionState = .disconnected
    @Published var showThinkingSteps = false
    @Published var currentShimmerLabel: String? = nil
    @Published var showLoginFlow = false

    // MARK: Dependencies

    private let webSocket: any WebSocketServiceProtocol
    private let messageStore: MessageStore
    private let serverURL: URL
    let loginFlowViewModel: LoginFlowViewModel

    // MARK: Internal state

    private var cancellables = Set<AnyCancellable>()
    private var currentStreamingMessageId: UUID?
    private var sessionId: String = UUID().uuidString

    // MARK: - Init

    init(
        webSocket: (any WebSocketServiceProtocol)? = nil,
        messageStore: MessageStore = MessageStore(),
        serverURL: URL = URL(string: "ws://localhost:8080")!
    ) {
        let ws = webSocket ?? WebSocketService()
        self.webSocket = ws
        self.messageStore = messageStore
        self.serverURL = serverURL
        self.loginFlowViewModel = LoginFlowViewModel(webSocket: ws)
        setupSubscriptions()
    }

    // MARK: - Public API

    func connect() {
        webSocket.connect(to: serverURL)
    }

    func disconnect() {
        webSocket.disconnect()
    }

    func sendMessage(_ text: String) {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, !isStreaming else { return }

        let userMessage = ChatMessage(role: .user, content: trimmed)
        messages.append(userMessage)
        persistMessages()

        webSocket.sendChatMessage(text: trimmed)
    }

    func loadMessages(sessionId: String? = nil) async {
        if let sessionId { self.sessionId = sessionId }
        do {
            let loaded = try await messageStore.load(sessionId: self.sessionId)
            messages = loaded
        } catch {
            log("failed to load messages: \(error.localizedDescription)")
        }
    }

    // MARK: - Subscriptions

    private func setupSubscriptions() {
        webSocket.statePublisher
            .receive(on: DispatchQueue.main)
            .sink { [weak self] state in
                self?.connectionState = state
            }
            .store(in: &cancellables)

        webSocket.streamEventPublisher
            .receive(on: DispatchQueue.main)
            .sink { [weak self] event in
                self?.handleEvent(event)
            }
            .store(in: &cancellables)
    }

    // MARK: - Event handling

    private func handleEvent(_ event: StreamEvent) {
        switch event {
        case .assistantDelta(let delta):
            handleDelta(delta)
        case .lifecycle(let status, _):
            handleLifecycle(status: status)
        case .stateDelta(let step):
            handleStateDelta(step)
        case .taskUpdate(_, _, let step):
            if let step {
                handleThinkingStep(step)
            }
        case .toolStarted(let toolName, let description):
            let step = ThinkingStep(
                id: UUID().uuidString, description: description,
                status: .running, toolName: toolName,
                timestamp: ISO8601DateFormatter().string(from: Date()))
            handleThinkingStep(step)
            currentShimmerLabel = description
        case .toolCompleted(let toolName, let success, let summary):
            let step = ThinkingStep(
                id: UUID().uuidString, description: summary,
                status: success ? .done : .error, toolName: toolName,
                timestamp: ISO8601DateFormatter().string(from: Date()))
            handleThinkingStep(step)
        case .cardCreated(let cardDict):
            handleCardCreated(cardDict)
        case .approvalRequested:
            break // handled elsewhere
        case .loginFrame(let imageBase64, let url, let profile, let pageTitle, let elements):
            loginFlowViewModel.handleFrame(
                imageBase64: imageBase64, url: url, profile: profile,
                pageTitle: pageTitle, elements: elements
            )
            if !showLoginFlow {
                showLoginFlow = true
            }
        case .loginFlowEnd(let profile, let authenticated, let domain):
            loginFlowViewModel.isActive = false
            showLoginFlow = false
            if authenticated {
                let msg = ChatMessage(role: .assistant, content: "Successfully logged into \(domain).")
                messages.append(msg)
                persistMessages()
            }
        case .unknown:
            break
        }
    }

    private func handleLifecycle(status: String) {
        if status == "start" {
            isStreaming = true
            showThinkingSteps = true
            thinkingSteps = []
            currentShimmerLabel = "Thinking..."

            let placeholder = ChatMessage.assistantPlaceholder()
            currentStreamingMessageId = placeholder.id
            messages.append(placeholder)
        } else if status == "end" {
            isStreaming = false
            currentShimmerLabel = nil

            // Finalize streaming message
            if let id = currentStreamingMessageId,
               let index = messages.firstIndex(where: { $0.id == id }) {
                messages[index].isStreaming = false
                // Remove empty assistant messages
                if messages[index].content.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                    messages.remove(at: index)
                }
            }
            currentStreamingMessageId = nil
            persistMessages()

            // Fade thinking steps after a short delay
            Task {
                try? await Task.sleep(nanoseconds: 2_000_000_000)
                showThinkingSteps = false
            }
        }
    }

    private func handleDelta(_ delta: String) {
        // First text delta means agent is responding, not just thinking
        currentShimmerLabel = nil

        guard let id = currentStreamingMessageId,
              let index = messages.firstIndex(where: { $0.id == id }) else {
            // No placeholder yet — create one
            let placeholder = ChatMessage.assistantPlaceholder()
            currentStreamingMessageId = placeholder.id
            messages.append(placeholder)
            if var last = messages.last {
                last.content += delta
                messages[messages.count - 1] = last
            }
            return
        }
        messages[index].content += delta
    }

    private func handleStateDelta(_ step: ThinkingStep) {
        currentShimmerLabel = step.description
        if let index = thinkingSteps.firstIndex(where: { $0.id == step.id }) {
            thinkingSteps[index] = step
        } else {
            thinkingSteps.append(step)
        }
    }

    private func handleThinkingStep(_ step: ThinkingStep) {
        if let index = thinkingSteps.firstIndex(where: { $0.id == step.id }) {
            thinkingSteps[index] = step
        } else {
            thinkingSteps.append(step)
        }
    }

    // MARK: - Card decoding

    private func handleCardCreated(_ cardDict: [String: AnyCodable]) {
        do {
            let jsonData = try JSONEncoder().encode(cardDict)
            let anyCard = try JSONDecoder().decode(AnyCard.self, from: jsonData)
            let cardMessage = ChatMessage(role: .assistant, content: "", card: anyCard)
            messages.append(cardMessage)
            persistMessages()
        } catch {
            log("Failed to decode card: \(error)")
            if let raw = try? JSONEncoder().encode(cardDict),
               let str = String(data: raw, encoding: .utf8) {
                log("Raw card payload: \(str)")
            }
        }
    }

    // MARK: - Persistence

    private func persistMessages() {
        let msgs = messages
        let id = sessionId
        Task {
            do {
                try await messageStore.save(msgs, sessionId: id)
            } catch {
                log("failed to persist messages: \(error.localizedDescription)")
            }
        }
    }

    private func log(_ message: String) {
        #if DEBUG
        print("[ChatViewModel] \(message)")
        #endif
    }
}
