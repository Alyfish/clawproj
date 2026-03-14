import Foundation
import Combine

/// Listens for `credential/request` events from the agent via WebSocket
/// and auto-responds with stored credentials from the Keychain.
/// Credentials are nil'd out immediately after sending.
@MainActor
final class CredentialRequestHandler: ObservableObject {

    private let webSocket: any WebSocketServiceProtocol
    private let credentialStore: CredentialStore
    private var cancellable: AnyCancellable?

    // MARK: - Init

    init(webSocket: any WebSocketServiceProtocol, credentialStore: CredentialStore = .shared) {
        self.webSocket = webSocket
        self.credentialStore = credentialStore
    }

    // MARK: - Start

    /// Subscribe to credential request events. Call once after WebSocket connects.
    func start() {
        guard cancellable == nil else { return }
        cancellable = webSocket.streamEventPublisher
            .receive(on: DispatchQueue.main)
            .sink { [weak self] event in
                guard let self else { return }
                if case .credentialRequested(let requestId, let domain, let reason) = event {
                    self.handleCredentialRequest(requestId: requestId, domain: domain, reason: reason)
                }
            }
    }

    // MARK: - Handle

    private func handleCredentialRequest(requestId: String, domain: String, reason: String) {
        #if DEBUG
        print("[CredentialRequestHandler] credential/request for \(domain) (reason: \(reason))")
        #endif

        var credentials = credentialStore.getCredentials(for: domain)

        if credentials.isEmpty {
            webSocket.sendCredentialNone(requestId: requestId, domain: domain, reason: "no_credentials")
        } else {
            webSocket.sendCredentialResponse(
                requestId: requestId,
                domain: domain,
                credentials: credentials
            )
        }

        // SECURITY: nil out credential data after send
        credentials = []
    }
}
