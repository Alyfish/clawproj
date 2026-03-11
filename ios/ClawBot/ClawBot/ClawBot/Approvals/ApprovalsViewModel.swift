import Foundation
import Combine

@MainActor
final class ApprovalsViewModel: ObservableObject {

    // MARK: - Published state

    @Published var pending: [ApprovalRequest] = []
    @Published var history: [ResolvedApproval] = []
    @Published var selectedApproval: ApprovalRequest?

    // MARK: - Computed

    var pendingCount: Int { pending.count }

    // MARK: - Private

    private let webSocket: any WebSocketServiceProtocol
    private let approvalStore: ApprovalStore
    private let notificationManager: NotificationManager
    private var cancellables = Set<AnyCancellable>()
    private var deepLinkCancellable: AnyCancellable?

    // MARK: - Init

    init(
        webSocket: any WebSocketServiceProtocol,
        approvalStore: ApprovalStore = ApprovalStore(),
        notificationManager: NotificationManager? = nil
    ) {
        self.webSocket = webSocket
        self.approvalStore = approvalStore
        self.notificationManager = notificationManager ?? NotificationManager.shared

        webSocket.streamEventPublisher
            .receive(on: DispatchQueue.main)
            .sink { [weak self] event in
                self?.handleEvent(event)
            }
            .store(in: &cancellables)

        deepLinkCancellable = NotificationCenter.default.publisher(
            for: .deepLinkToApproval
        )
        .receive(on: DispatchQueue.main)
        .sink { [weak self] notification in
            guard let approvalId = notification.userInfo?["approvalId"] as? String else { return }
            self?.navigateToApproval(id: approvalId)
        }
    }

    // MARK: - Public actions

    func approve(_ approvalId: String) {
        webSocket.sendApprovalResponse(approvalId: approvalId, decision: "approved")
        moveToHistory(approvalId: approvalId, decision: .approved)
    }

    func deny(_ approvalId: String) {
        webSocket.sendApprovalResponse(approvalId: approvalId, decision: "denied")
        moveToHistory(approvalId: approvalId, decision: .denied)
    }

    // MARK: - Event handling

    private func handleEvent(_ event: StreamEvent) {
        switch event {
        case .approvalRequested(let id, let taskId, let action, let description, let details):
            let detailStrings = details.reduce(into: [String: String]()) { result, pair in
                if let str = pair.value.stringValue {
                    result[pair.key] = str
                } else {
                    result[pair.key] = "\(pair.value.value)"
                }
            }

            guard let approvalAction = ApprovalAction(rawValue: action) else { return }
            let request = ApprovalRequest(
                id: id,
                taskId: taskId,
                action: approvalAction,
                description: description,
                details: detailStrings,
                createdAt: ISO8601DateFormatter().string(from: Date())
            )

            if !pending.contains(where: { $0.id == id }) {
                pending.append(request)
                persistApprovals()
            }

            notificationManager.sendLocalApprovalNotification(
                approvalId: id,
                title: "Action Required: \(approvalAction.displayName)",
                body: description
            )
            notificationManager.updateBadge(count: pendingCount)

        default:
            break
        }
    }

    // MARK: - Navigation

    func navigateToApproval(id: String) {
        if let request = pending.first(where: { $0.id == id }) {
            selectedApproval = request
        }
    }

    // MARK: - Private helpers

    private func moveToHistory(approvalId: String, decision: ApprovalDecision) {
        guard let index = pending.firstIndex(where: { $0.id == approvalId }) else { return }
        let request = pending.remove(at: index)

        let response = ApprovalResponse(
            id: approvalId,
            decision: decision,
            decidedAt: ISO8601DateFormatter().string(from: Date())
        )
        let resolved = ResolvedApproval(request: request, response: response)
        history.insert(resolved, at: 0)

        notificationManager.updateBadge(count: pendingCount)
        persistApprovals()

        if selectedApproval?.id == approvalId {
            selectedApproval = nil
        }
    }

    // MARK: - Persistence

    /// Load persisted data from disk. Uses isEmpty guards to avoid overwriting live WebSocket data.
    func loadPersistedData() async {
        do {
            let data = try await approvalStore.load()
            if pending.isEmpty { pending = data.pending }
            if history.isEmpty { history = data.history }
        } catch {
            log("failed to load approvals: \(error.localizedDescription)")
        }
    }

    private func persistApprovals() {
        let currentPending = pending
        let currentHistory = history
        Task {
            do {
                try await approvalStore.save(pending: currentPending, history: currentHistory)
            } catch {
                log("failed to persist approvals: \(error.localizedDescription)")
            }
        }
    }

    private func log(_ message: String) {
        #if DEBUG
        print("[ApprovalsViewModel] \(message)")
        #endif
    }

    // MARK: - Mock data (until real gateway is connected)

    private func loadMockData() {
        pending = [.mockSubmit, .mockPay, .mockDelete]
        history = [.mockApproved, .mockDenied]
    }
}

// MARK: - ApprovalRequest + Hashable

extension ApprovalRequest: Hashable {
    func hash(into hasher: inout Hasher) {
        hasher.combine(id)
    }
}
