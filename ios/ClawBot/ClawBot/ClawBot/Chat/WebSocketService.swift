import Foundation
import Combine

// MARK: - ConnectionState

enum ConnectionState: String {
    case disconnected
    case connecting
    case connected
    case reconnecting
}

// MARK: - WebSocketServiceProtocol

protocol WebSocketServiceProtocol: AnyObject {
    var state: ConnectionState { get }

    // Publishers
    var statePublisher: AnyPublisher<ConnectionState, Never> { get }
    var messagePublisher: AnyPublisher<WSMessage, Never> { get }
    var streamEventPublisher: AnyPublisher<StreamEvent, Never> { get }

    // Lifecycle
    func connect(to url: URL)
    func disconnect()

    // Sending
    func send(_ message: WSMessage)
    func sendChatMessage(text: String)
    func sendApprovalResponse(approvalId: String, decision: String)
    func sendTaskStop(taskId: String)
    func sendLoginInput(profile: String, ref: Int, text: String)
    func sendLoginClick(profile: String, ref: Int)
    func sendLoginDone(profile: String)
    func sendCardAction(action: String, cardType: String, cardData: [String: AnyCodable])
    func fetchWatchlistAlerts()
    func markWatchlistAlertsRead(alertIds: [String])
    func markAllWatchlistAlertsRead()
}

// MARK: - WebSocketService

final class WebSocketService: ObservableObject, WebSocketServiceProtocol {

    // MARK: Published state

    @Published private(set) var state: ConnectionState = .disconnected

    // MARK: Combine subjects

    private let stateSubject = CurrentValueSubject<ConnectionState, Never>(.disconnected)
    private let messageSubject = PassthroughSubject<WSMessage, Never>()
    private let streamEventSubject = PassthroughSubject<StreamEvent, Never>()

    var statePublisher: AnyPublisher<ConnectionState, Never> {
        stateSubject.eraseToAnyPublisher()
    }
    var messagePublisher: AnyPublisher<WSMessage, Never> {
        messageSubject.eraseToAnyPublisher()
    }
    var streamEventPublisher: AnyPublisher<StreamEvent, Never> {
        streamEventSubject.eraseToAnyPublisher()
    }

    // MARK: Connection state

    private var webSocketTask: URLSessionWebSocketTask?
    private var session: URLSession = .shared
    private var serverURL: URL?
    private var deviceToken: String?
    private var sessionId: String?

    // MARK: Reconnection

    private var intentionalDisconnect = false
    private var reconnectAttempts = 0
    private let maxBackoff: TimeInterval = 30.0
    private var reconnectTask: Task<Void, Never>?

    // MARK: - Lifecycle

    func connect(to url: URL) {
        guard state == .disconnected || state == .reconnecting else { return }
        serverURL = url
        intentionalDisconnect = false
        updateState(.connecting)
        openWebSocket(url: url)
    }

    func disconnect() {
        intentionalDisconnect = true
        reconnectTask?.cancel()
        reconnectTask = nil
        reconnectAttempts = 0
        webSocketTask?.cancel(with: .normalClosure, reason: nil)
        webSocketTask = nil
        updateState(.disconnected)
    }

    // MARK: - Sending

    func send(_ message: WSMessage) {
        guard state == .connected, let task = webSocketTask else { return }
        do {
            let data = try JSONEncoder().encode(message)
            guard let text = String(data: data, encoding: .utf8) else { return }
            task.send(.string(text)) { [weak self] error in
                if let error {
                    self?.log("send error: \(error.localizedDescription)")
                }
            }
        } catch {
            log("encode error: \(error.localizedDescription)")
        }
    }

    func sendChatMessage(text: String) {
        let message = WSMessage.request(
            method: "chat.send",
            id: UUID().uuidString,
            payload: [
                "text": AnyCodable(text),
                "idempotencyKey": AnyCodable(UUID().uuidString),
            ]
        )
        send(message)
    }

    func sendApprovalResponse(approvalId: String, decision: String) {
        let message = WSMessage.request(
            method: "approval.resolve",
            id: UUID().uuidString,
            payload: [
                "approvalId": AnyCodable(approvalId),
                "decision": AnyCodable(decision),
            ]
        )
        send(message)
    }

    func sendTaskStop(taskId: String) {
        let message = WSMessage.request(
            method: "task.stop",
            id: UUID().uuidString,
            payload: [
                "taskId": AnyCodable(taskId),
            ]
        )
        send(message)
    }

    func sendLoginInput(profile: String, ref: Int, text: String) {
        let message = WSMessage.request(
            method: "login.input",
            id: UUID().uuidString,
            payload: [
                "profile": AnyCodable(profile),
                "ref": AnyCodable(ref),
                "text": AnyCodable(text),
            ]
        )
        send(message)
    }

    func sendLoginClick(profile: String, ref: Int) {
        let message = WSMessage.request(
            method: "login.click",
            id: UUID().uuidString,
            payload: [
                "profile": AnyCodable(profile),
                "ref": AnyCodable(ref),
            ]
        )
        send(message)
    }

    func sendLoginDone(profile: String) {
        let message = WSMessage.request(
            method: "login.done",
            id: UUID().uuidString,
            payload: [
                "profile": AnyCodable(profile),
            ]
        )
        send(message)
    }

    func sendCardAction(action: String, cardType: String, cardData: [String: AnyCodable]) {
        let message = WSMessage.request(
            method: "card.action",
            id: UUID().uuidString,
            payload: [
                "action": AnyCodable(action),
                "cardType": AnyCodable(cardType),
                "cardData": AnyCodable(cardData.mapValues { $0.value }),
            ]
        )
        send(message)
    }

    func fetchWatchlistAlerts() {
        let message = WSMessage.request(
            method: "watchlist.alerts.fetch",
            id: UUID().uuidString,
            payload: [:]
        )
        send(message)
    }

    func markWatchlistAlertsRead(alertIds: [String]) {
        let message = WSMessage.request(
            method: "watchlist.alerts.markRead",
            id: UUID().uuidString,
            payload: [
                "alertIds": AnyCodable(alertIds),
            ]
        )
        send(message)
    }

    func markAllWatchlistAlertsRead() {
        let message = WSMessage.request(
            method: "watchlist.alerts.markRead",
            id: UUID().uuidString,
            payload: [
                "all": AnyCodable(true),
            ]
        )
        send(message)
    }

    // MARK: - Private: WebSocket lifecycle

    private func openWebSocket(url: URL) {
        let task = session.webSocketTask(with: url)
        webSocketTask = task
        task.resume()
        sendHandshake()
        receiveLoop()
    }

    private func sendHandshake() {
        var payload: [String: AnyCodable] = [
            "role": AnyCodable("operator"),
            "scopes": AnyCodable(["chat", "approval", "task"]),
        ]
        if let deviceToken {
            payload["deviceToken"] = AnyCodable(deviceToken)
        }
        if let sessionId {
            payload["sessionId"] = AnyCodable(sessionId)
        }

        let handshake = WSMessage.request(
            method: "connect",
            id: UUID().uuidString,
            payload: payload
        )
        forceSend(handshake)
    }

    /// Sends a message bypassing the `.connected` state check (used for handshake).
    private func forceSend(_ message: WSMessage) {
        guard let task = webSocketTask else { return }
        do {
            let data = try JSONEncoder().encode(message)
            guard let text = String(data: data, encoding: .utf8) else { return }
            task.send(.string(text)) { [weak self] error in
                if let error {
                    self?.log("handshake send error: \(error.localizedDescription)")
                }
            }
        } catch {
            log("handshake encode error: \(error.localizedDescription)")
        }
    }

    private func receiveLoop() {
        webSocketTask?.receive { [weak self] result in
            guard let self else { return }
            switch result {
            case .success(let message):
                self.handleReceived(message)
                self.receiveLoop()
            case .failure(let error):
                self.log("receive error: \(error.localizedDescription)")
                self.handleConnectionLost()
            }
        }
    }

    private func handleReceived(_ message: URLSessionWebSocketTask.Message) {
        let data: Data
        switch message {
        case .string(let text):
            guard let d = text.data(using: .utf8) else { return }
            data = d
        case .data(let d):
            data = d
        @unknown default:
            return
        }

        guard let wsMessage = try? JSONDecoder().decode(WSMessage.self, from: data) else {
            log("failed to decode WSMessage")
            return
        }

        // Handle connect response — extract deviceToken and sessionId
        if wsMessage.type == .res, wsMessage.method == "connect" {
            if let payload = wsMessage.payload {
                deviceToken = payload["deviceToken"]?.stringValue
                sessionId = payload["sessionId"]?.stringValue
            }
            reconnectAttempts = 0
            updateState(.connected)
            // Fetch any missed watchlist alerts on (re)connect
            fetchWatchlistAlerts()
        }

        // Handle watchlist alerts fetch response — emit each as a stream event
        if wsMessage.type == .res, wsMessage.method == "watchlist.alerts.fetch" {
            if let alerts = wsMessage.payload?["alerts"]?.value as? [[String: Any]] {
                for alertDict in alerts {
                    let payload = alertDict.mapValues { AnyCodable($0) }
                    let alert = WatchlistAlert(
                        id: payload["id"]?.stringValue ?? UUID().uuidString,
                        watchId: payload["watchId"]?.stringValue ?? "",
                        alertType: payload["alertType"]?.stringValue ?? "general_change",
                        title: payload["title"]?.stringValue ?? "",
                        message: payload["message"]?.stringValue ?? "",
                        source: payload["source"]?.stringValue ?? "",
                        previousValue: payload["previousValue"]?.stringValue,
                        currentValue: payload["currentValue"]?.stringValue,
                        url: payload["url"]?.stringValue,
                        cardType: payload["cardType"]?.stringValue,
                        timestamp: payload["createdAt"]?.stringValue
                            ?? ISO8601DateFormatter().string(from: Date())
                    )
                    streamEventSubject.send(.watchlistAlert(alert: alert))
                }
            }
        }

        // Publish the raw message
        messageSubject.send(wsMessage)

        // Parse and publish stream events
        if let event = StreamEvent.from(wsMessage) {
            streamEventSubject.send(event)
        }
    }

    // MARK: - Reconnection

    private func handleConnectionLost() {
        webSocketTask = nil
        guard !intentionalDisconnect else {
            updateState(.disconnected)
            return
        }
        attemptReconnect()
    }

    private func attemptReconnect() {
        guard let url = serverURL else {
            updateState(.disconnected)
            return
        }

        updateState(.reconnecting)
        let delay = min(pow(2.0, Double(reconnectAttempts)), maxBackoff)
        reconnectAttempts += 1

        reconnectTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: UInt64(delay * 1_000_000_000))
            guard let self, !Task.isCancelled else { return }
            await MainActor.run {
                self.updateState(.connecting)
            }
            self.openWebSocket(url: url)
        }
    }

    // MARK: - Helpers

    private func updateState(_ newState: ConnectionState) {
        if Thread.isMainThread {
            state = newState
            stateSubject.send(newState)
        } else {
            DispatchQueue.main.async { [weak self] in
                self?.state = newState
                self?.stateSubject.send(newState)
            }
        }
    }

    private func log(_ message: String) {
        #if DEBUG
        print("[WebSocketService] \(message)")
        #endif
    }
}

// MARK: - MockWebSocketService

final class MockWebSocketService: WebSocketServiceProtocol {

    var state: ConnectionState = .disconnected

    private let stateSubject = CurrentValueSubject<ConnectionState, Never>(.disconnected)
    private let messageSubject = PassthroughSubject<WSMessage, Never>()
    private let streamEventSubject = PassthroughSubject<StreamEvent, Never>()

    var statePublisher: AnyPublisher<ConnectionState, Never> {
        stateSubject.eraseToAnyPublisher()
    }
    var messagePublisher: AnyPublisher<WSMessage, Never> {
        messageSubject.eraseToAnyPublisher()
    }
    var streamEventPublisher: AnyPublisher<StreamEvent, Never> {
        streamEventSubject.eraseToAnyPublisher()
    }

    // Recorded calls for test assertions
    private(set) var connectCalled = false
    private(set) var disconnectCalled = false
    private(set) var sentMessages: [WSMessage] = []

    func connect(to url: URL) {
        connectCalled = true
        state = .connected
        stateSubject.send(.connected)
    }

    func disconnect() {
        disconnectCalled = true
        state = .disconnected
        stateSubject.send(.disconnected)
    }

    func send(_ message: WSMessage) {
        sentMessages.append(message)
    }

    func sendChatMessage(text: String) {
        let message = WSMessage.request(
            method: "chat.send",
            id: UUID().uuidString,
            payload: [
                "text": AnyCodable(text),
                "idempotencyKey": AnyCodable(UUID().uuidString),
            ]
        )
        sentMessages.append(message)
    }

    func sendApprovalResponse(approvalId: String, decision: String) {
        let message = WSMessage.request(
            method: "approval.resolve",
            id: UUID().uuidString,
            payload: [
                "approvalId": AnyCodable(approvalId),
                "decision": AnyCodable(decision),
            ]
        )
        sentMessages.append(message)
    }

    func sendTaskStop(taskId: String) {
        let message = WSMessage.request(
            method: "task.stop",
            id: UUID().uuidString,
            payload: [
                "taskId": AnyCodable(taskId),
            ]
        )
        sentMessages.append(message)
    }

    func sendLoginInput(profile: String, ref: Int, text: String) {
        let message = WSMessage.request(
            method: "login.input",
            id: UUID().uuidString,
            payload: [
                "profile": AnyCodable(profile),
                "ref": AnyCodable(ref),
                "text": AnyCodable(text),
            ]
        )
        sentMessages.append(message)
    }

    func sendLoginClick(profile: String, ref: Int) {
        let message = WSMessage.request(
            method: "login.click",
            id: UUID().uuidString,
            payload: [
                "profile": AnyCodable(profile),
                "ref": AnyCodable(ref),
            ]
        )
        sentMessages.append(message)
    }

    func sendLoginDone(profile: String) {
        let message = WSMessage.request(
            method: "login.done",
            id: UUID().uuidString,
            payload: [
                "profile": AnyCodable(profile),
            ]
        )
        sentMessages.append(message)
    }

    func sendCardAction(action: String, cardType: String, cardData: [String: AnyCodable]) {
        let message = WSMessage.request(
            method: "card.action",
            id: UUID().uuidString,
            payload: [
                "action": AnyCodable(action),
                "cardType": AnyCodable(cardType),
                "cardData": AnyCodable(cardData.mapValues { $0.value }),
            ]
        )
        sentMessages.append(message)
    }

    func fetchWatchlistAlerts() {
        let message = WSMessage.request(
            method: "watchlist.alerts.fetch",
            id: UUID().uuidString,
            payload: [:]
        )
        sentMessages.append(message)
    }

    func markWatchlistAlertsRead(alertIds: [String]) {
        let message = WSMessage.request(
            method: "watchlist.alerts.markRead",
            id: UUID().uuidString,
            payload: [
                "alertIds": AnyCodable(alertIds),
            ]
        )
        sentMessages.append(message)
    }

    func markAllWatchlistAlertsRead() {
        let message = WSMessage.request(
            method: "watchlist.alerts.markRead",
            id: UUID().uuidString,
            payload: [
                "all": AnyCodable(true),
            ]
        )
        sentMessages.append(message)
    }

    // MARK: - Test helpers

    func simulateMessage(_ message: WSMessage) {
        messageSubject.send(message)
    }

    func simulateStreamEvent(_ event: StreamEvent) {
        streamEventSubject.send(event)
    }

    func simulateStateChange(_ newState: ConnectionState) {
        state = newState
        stateSubject.send(newState)
    }
}
