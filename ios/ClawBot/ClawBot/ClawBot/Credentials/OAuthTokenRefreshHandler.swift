import Foundation
import Combine

/// Listens for `credential/token:refresh` events from the gateway via WebSocket
/// and auto-responds with a refreshed Google OAuth access token.
/// Token is nil'd out immediately after sending (security).
@MainActor
final class OAuthTokenRefreshHandler: ObservableObject {

    private let webSocket: any WebSocketServiceProtocol
    private let oauthManager: GoogleOAuthManager
    private var cancellable: AnyCancellable?

    // MARK: - Init

    init(webSocket: any WebSocketServiceProtocol, oauthManager: GoogleOAuthManager = .shared) {
        self.webSocket = webSocket
        self.oauthManager = oauthManager
    }

    // MARK: - Start

    /// Subscribe to token refresh events. Call once after WebSocket connects.
    func start() {
        guard cancellable == nil else { return }
        cancellable = webSocket.streamEventPublisher
            .receive(on: DispatchQueue.main)
            .sink { [weak self] event in
                guard let self else { return }
                if case .tokenRefreshRequested(let service, let requestId) = event {
                    self.handleTokenRefresh(service: service, requestId: requestId)
                }
            }
    }

    // MARK: - Handle

    private func handleTokenRefresh(service: String, requestId: String) {
        guard service == "google" else {
            #if DEBUG
            print("[OAuthTokenRefreshHandler] unknown service: \(service)")
            #endif
            return
        }

        #if DEBUG
        print("[OAuthTokenRefreshHandler] credential/token:refresh for \(service)")
        #endif

        Task {
            do {
                var token = try await oauthManager.refreshAccessToken()
                webSocket.sendTokenRefreshed(service: service, token: token, requestId: requestId)
                // SECURITY: nil out token after send
                token = ""
            } catch {
                #if DEBUG
                print("[OAuthTokenRefreshHandler] refresh failed: \(error.localizedDescription)")
                #endif
                webSocket.sendCredentialNone(
                    requestId: requestId,
                    domain: "oauth:\(service)",
                    reason: "no_credentials"
                )
            }
        }
    }
}
