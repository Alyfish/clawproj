import Foundation
import Security
import CryptoKit
import AuthenticationServices
import UIKit

// MARK: - GoogleOAuthError

enum GoogleOAuthError: Error, LocalizedError {
    case missingConfig
    case authFailed(String)
    case tokenExchangeFailed(String)
    case refreshFailed(revoked: Bool)
    case networkError(Error)

    var errorDescription: String? {
        switch self {
        case .missingConfig:
            return "Google OAuth client ID is not configured."
        case .authFailed(let reason):
            return "Authentication failed: \(reason)"
        case .tokenExchangeFailed(let reason):
            return "Token exchange failed: \(reason)"
        case .refreshFailed(let revoked):
            return revoked ? "Google access was revoked. Please reconnect." : "Token refresh failed."
        case .networkError(let error):
            return "Network error: \(error.localizedDescription)"
        }
    }
}

// MARK: - GoogleOAuthManager

/// Manages Google OAuth tokens for Google Workspace access.
/// Refresh token is stored in Keychain; access token is in-memory only.
/// Thread-safe via DispatchQueue — Keychain APIs are already thread-safe.
nonisolated final class GoogleOAuthManager {

    static let shared = GoogleOAuthManager()

    /// Notification posted when a refresh fails due to revoked access.
    /// UI should observe this to prompt re-authentication.
    static let tokenRevokedNotification = Notification.Name("GoogleOAuthTokenRevoked")

    // MARK: - Scopes

    static let scopes = [
        "email",
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/drive",
        "https://www.googleapis.com/auth/documents",
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/calendar",
        "https://www.googleapis.com/auth/presentations",
    ]

    // MARK: - Config

    /// Load OAuth config from GoogleOAuth-Config.plist bundled with the app.
    private static func loadConfig() -> [String: String] {
        guard let url = Bundle.main.url(forResource: "GoogleOAuth-Config", withExtension: "plist"),
              let data = try? Data(contentsOf: url),
              let dict = try? PropertyListSerialization.propertyList(from: data, format: nil) as? [String: String] else {
            return [:]
        }
        return dict
    }

    private let clientID: String?
    private let redirectURI: String?

    // MARK: - Keychain keys

    private static let keychainService = "com.clawbot.google-oauth"
    private static let keychainAccount = "refresh_token"
    private static let accessGroup = "group.com.clawbot.shared"

    // MARK: - In-memory state (protected by stateQueue)

    private let stateQueue = DispatchQueue(label: "com.clawbot.oauth.state")
    private var _accessToken: String?
    private var _tokenExpiry: Date?

    /// Google token endpoint.
    private static let tokenURL = URL(string: "https://oauth2.googleapis.com/token")!
    private static let userinfoURL = URL(string: "https://www.googleapis.com/oauth2/v3/userinfo")!
    private static let authBaseURL = "https://accounts.google.com/o/oauth2/v2/auth"

    // MARK: - Public accessors

    /// Current access token, or nil if not authenticated or expired.
    var currentAccessToken: String? {
        stateQueue.sync { _accessToken }
    }

    /// Whether a refresh token exists in Keychain (user has connected Google).
    var isAuthenticated: Bool {
        loadRefreshToken() != nil
    }

    /// Connected Google email, stored in UserDefaults.
    var userEmail: String? {
        get { UserDefaults.standard.string(forKey: "google_oauth_email") }
        set { UserDefaults.standard.set(newValue, forKey: "google_oauth_email") }
    }

    /// Whether the current access token is still valid.
    var isTokenValid: Bool {
        stateQueue.sync {
            guard let token = _accessToken, let expiry = _tokenExpiry else { return false }
            // Consider expired 60 seconds early to avoid race conditions
            return !token.isEmpty && expiry > Date().addingTimeInterval(60)
        }
    }

    // MARK: - Init

    init(clientID: String? = nil, redirectURI: String? = nil) {
        let config = Self.loadConfig()
        self.clientID = clientID ?? config["GOOGLE_OAUTH_CLIENT_ID"]
        self.redirectURI = redirectURI ?? config["GOOGLE_OAUTH_REDIRECT_URI"]
    }

    // MARK: - PKCE

    /// Generate a cryptographically random code verifier (43 chars, URL-safe base64).
    static func generateCodeVerifier() -> String {
        var bytes = [UInt8](repeating: 0, count: 32)
        _ = SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes)
        return Data(bytes).base64URLEncodedString()
    }

    /// SHA256 hash of the verifier, base64url-encoded (no padding).
    static func codeChallenge(from verifier: String) -> String {
        let data = Data(verifier.utf8)
        let hash = SHA256.hash(data: data)
        return Data(hash).base64URLEncodedString()
    }

    // MARK: - OAuth Flow

    /// Run the full Google OAuth flow: open browser → user consents → exchange code → store tokens.
    /// Must be called from the main thread. Throws on failure; returns silently if user cancels.
    @MainActor
    func authenticate() async throws {
        guard let clientID, !clientID.isEmpty,
              let redirectURI, !redirectURI.isEmpty else {
            throw GoogleOAuthError.missingConfig
        }

        let codeVerifier = Self.generateCodeVerifier()
        let challenge = Self.codeChallenge(from: codeVerifier)
        let scopeString = Self.scopes.joined(separator: " ")

        var components = URLComponents(string: Self.authBaseURL)!
        components.queryItems = [
            URLQueryItem(name: "client_id", value: clientID),
            URLQueryItem(name: "redirect_uri", value: redirectURI),
            URLQueryItem(name: "response_type", value: "code"),
            URLQueryItem(name: "scope", value: scopeString),
            URLQueryItem(name: "code_challenge", value: challenge),
            URLQueryItem(name: "code_challenge_method", value: "S256"),
            URLQueryItem(name: "access_type", value: "offline"),
            URLQueryItem(name: "prompt", value: "consent"),
        ]

        guard let authURL = components.url else {
            throw GoogleOAuthError.authFailed("Failed to build authorization URL")
        }

        let callbackScheme = URL(string: redirectURI)?.scheme

        // Run ASWebAuthenticationSession via continuation
        let callbackURL: URL = try await withCheckedThrowingContinuation { continuation in
            let session = ASWebAuthenticationSession(
                url: authURL,
                callbackURLScheme: callbackScheme
            ) { callbackURL, error in
                if let error = error as? ASWebAuthenticationSessionError,
                   error.code == .canceledLogin {
                    continuation.resume(throwing: GoogleOAuthError.authFailed("cancelled"))
                    return
                }
                if let error {
                    continuation.resume(throwing: GoogleOAuthError.authFailed(error.localizedDescription))
                    return
                }
                guard let callbackURL else {
                    continuation.resume(throwing: GoogleOAuthError.authFailed("No callback URL"))
                    return
                }
                continuation.resume(returning: callbackURL)
            }

            let contextProvider = WindowPresentationContext()
            session.presentationContextProvider = contextProvider
            session.prefersEphemeralWebBrowserSession = false

            // Retain context provider until session completes
            objc_setAssociatedObject(session, "contextProvider", contextProvider, .OBJC_ASSOCIATION_RETAIN)

            session.start()
        }

        // Extract code from callback
        guard let code = Self.extractCode(from: callbackURL) else {
            throw GoogleOAuthError.authFailed("No authorization code in callback")
        }

        // Exchange code for tokens
        try await exchangeCodeForTokens(code: code, codeVerifier: codeVerifier)
    }

    /// Extract the authorization code from the callback URL.
    static func extractCode(from callbackURL: URL) -> String? {
        let components = URLComponents(url: callbackURL, resolvingAgainstBaseURL: false)
        return components?.queryItems?.first(where: { $0.name == "code" })?.value
    }

    // MARK: - Token Exchange

    /// Exchange an authorization code for access + refresh tokens.
    func exchangeCodeForTokens(code: String, codeVerifier: String) async throws {
        guard let clientID, let redirectURI else {
            throw GoogleOAuthError.missingConfig
        }

        let body = [
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirectURI,
            "client_id": clientID,
            "code_verifier": codeVerifier,
        ]

        let (data, response) = try await postForm(url: Self.tokenURL, body: body)

        guard let httpResponse = response as? HTTPURLResponse,
              httpResponse.statusCode == 200 else {
            let errorBody = String(data: data, encoding: .utf8) ?? "unknown"
            throw GoogleOAuthError.tokenExchangeFailed(errorBody)
        }

        let json = try JSONSerialization.jsonObject(with: data) as? [String: Any] ?? [:]

        guard let accessToken = json["access_token"] as? String else {
            throw GoogleOAuthError.tokenExchangeFailed("Missing access_token")
        }

        let refreshToken = json["refresh_token"] as? String
        let expiresIn = json["expires_in"] as? Int ?? 3600

        // Store tokens
        stateQueue.sync {
            _accessToken = accessToken
            _tokenExpiry = Date().addingTimeInterval(TimeInterval(expiresIn))
        }

        if let refreshToken {
            saveRefreshToken(refreshToken)
        }

        // Fetch user email
        if let email = try? await fetchUserEmail(accessToken: accessToken) {
            userEmail = email
        }
    }

    // MARK: - Token Refresh

    /// Refresh the access token using the stored refresh token.
    /// Returns the new access token.
    @discardableResult
    func refreshAccessToken() async throws -> String {
        guard let clientID else {
            throw GoogleOAuthError.missingConfig
        }

        guard let refreshToken = loadRefreshToken() else {
            throw GoogleOAuthError.refreshFailed(revoked: false)
        }

        let body = [
            "grant_type": "refresh_token",
            "refresh_token": refreshToken,
            "client_id": clientID,
        ]

        let (data, response): (Data, URLResponse)
        do {
            (data, response) = try await postForm(url: Self.tokenURL, body: body)
        } catch {
            throw GoogleOAuthError.networkError(error)
        }

        guard let httpResponse = response as? HTTPURLResponse else {
            throw GoogleOAuthError.refreshFailed(revoked: false)
        }

        if httpResponse.statusCode == 400 || httpResponse.statusCode == 401 {
            // Token likely revoked — clear everything
            signOut()
            NotificationCenter.default.post(name: Self.tokenRevokedNotification, object: nil)
            throw GoogleOAuthError.refreshFailed(revoked: true)
        }

        guard httpResponse.statusCode == 200 else {
            throw GoogleOAuthError.refreshFailed(revoked: false)
        }

        let json = try JSONSerialization.jsonObject(with: data) as? [String: Any] ?? [:]

        guard let accessToken = json["access_token"] as? String else {
            throw GoogleOAuthError.refreshFailed(revoked: false)
        }

        let expiresIn = json["expires_in"] as? Int ?? 3600

        stateQueue.sync {
            _accessToken = accessToken
            _tokenExpiry = Date().addingTimeInterval(TimeInterval(expiresIn))
        }

        return accessToken
    }

    /// Silently refresh the token if a refresh token exists.
    /// Called on app launch to ensure a valid access token is available.
    func refreshIfNeeded() async {
        guard isAuthenticated, !isTokenValid else { return }
        _ = try? await refreshAccessToken()
    }

    // MARK: - User Info

    /// Fetch the user's email from Google's userinfo endpoint.
    func fetchUserEmail(accessToken: String) async throws -> String? {
        var request = URLRequest(url: Self.userinfoURL)
        request.setValue("Bearer \(accessToken)", forHTTPHeaderField: "Authorization")

        let (data, _) = try await URLSession.shared.data(for: request)
        let json = try JSONSerialization.jsonObject(with: data) as? [String: Any] ?? [:]
        return json["email"] as? String
    }

    // MARK: - Sign Out

    /// Clear all stored tokens and user data.
    func signOut() {
        deleteRefreshToken()
        stateQueue.sync {
            _accessToken = nil
            _tokenExpiry = nil
        }
        userEmail = nil
    }

    // MARK: - Keychain: Refresh Token

    @discardableResult
    private func saveRefreshToken(_ token: String) -> Bool {
        guard let data = token.data(using: .utf8) else { return false }

        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: Self.keychainService,
            kSecAttrAccount as String: Self.keychainAccount,
            kSecAttrAccessGroup as String: Self.accessGroup,
        ]

        let updateAttrs: [String: Any] = [
            kSecValueData as String: data,
            kSecAttrAccessible as String: kSecAttrAccessibleWhenUnlockedThisDeviceOnly,
        ]

        let updateStatus = SecItemUpdate(query as CFDictionary, updateAttrs as CFDictionary)
        if updateStatus == errSecSuccess { return true }

        if updateStatus == errSecItemNotFound {
            var addQuery = query
            addQuery[kSecValueData as String] = data
            addQuery[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
            return SecItemAdd(addQuery as CFDictionary, nil) == errSecSuccess
        }

        return false
    }

    func loadRefreshToken() -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: Self.keychainService,
            kSecAttrAccount as String: Self.keychainAccount,
            kSecAttrAccessGroup as String: Self.accessGroup,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]

        var result: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &result)

        guard status == errSecSuccess,
              let data = result as? Data,
              let token = String(data: data, encoding: .utf8) else {
            return nil
        }
        return token
    }

    @discardableResult
    private func deleteRefreshToken() -> Bool {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: Self.keychainService,
            kSecAttrAccount as String: Self.keychainAccount,
            kSecAttrAccessGroup as String: Self.accessGroup,
        ]
        let status = SecItemDelete(query as CFDictionary)
        return status == errSecSuccess || status == errSecItemNotFound
    }

    // MARK: - Network Helpers

    private func postForm(url: URL, body: [String: String]) async throws -> (Data, URLResponse) {
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/x-www-form-urlencoded", forHTTPHeaderField: "Content-Type")

        let bodyString = body.map { key, value in
            "\(key.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? key)=\(value.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? value)"
        }.joined(separator: "&")

        request.httpBody = bodyString.data(using: .utf8)

        return try await URLSession.shared.data(for: request)
    }
}

// MARK: - ASWebAuthenticationSession Presentation Context

private class WindowPresentationContext: NSObject, ASWebAuthenticationPresentationContextProviding {
    func presentationAnchor(for session: ASWebAuthenticationSession) -> ASPresentationAnchor {
        UIApplication.shared.connectedScenes
            .compactMap { $0 as? UIWindowScene }
            .flatMap(\.windows)
            .first(where: \.isKeyWindow) ?? ASPresentationAnchor()
    }
}

// MARK: - Data Extension

extension Data {
    func base64URLEncodedString() -> String {
        base64EncodedString()
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
    }
}
