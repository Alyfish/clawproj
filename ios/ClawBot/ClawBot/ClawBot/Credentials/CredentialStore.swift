import Foundation
import Security
import AuthenticationServices

/// Keychain-backed credential store shared between main app and AutoFill extension.
/// Uses kSecClassInternetPassword with shared access group for cross-target access.
/// All methods are nonisolated — Security framework Keychain APIs are thread-safe.
nonisolated final class CredentialStore {

    /// Shared access group used by both main app and AutoFill extension.
    /// Must match the value in SharedKeys.appGroupSuite.
    private static let defaultAccessGroup = "group.com.clawbot.shared"

    static let shared = CredentialStore()

    private let accessGroup: String

    // MARK: - Init

    init(accessGroup: String = CredentialStore.defaultAccessGroup) {
        self.accessGroup = accessGroup
    }

    // MARK: - Save

    /// Save a credential to the Keychain. Updates existing entry if domain+username match.
    @discardableResult
    func save(domain: String, username: String, password: String) -> Bool {
        guard let passwordData = password.data(using: .utf8) else { return false }

        let query: [String: Any] = [
            kSecClass as String: kSecClassInternetPassword,
            kSecAttrServer as String: domain,
            kSecAttrAccount as String: username,
            kSecAttrAccessGroup as String: accessGroup,
        ]

        let updateAttrs: [String: Any] = [
            kSecValueData as String: passwordData,
            kSecAttrAccessible as String: kSecAttrAccessibleWhenUnlockedThisDeviceOnly,
        ]

        let updateStatus = SecItemUpdate(query as CFDictionary, updateAttrs as CFDictionary)

        if updateStatus == errSecSuccess {
            updateIdentityStore(domain: domain, username: username)
            return true
        }

        if updateStatus == errSecItemNotFound {
            var addQuery = query
            addQuery[kSecValueData as String] = passwordData
            addQuery[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly

            let addStatus = SecItemAdd(addQuery as CFDictionary, nil)
            if addStatus == errSecSuccess {
                updateIdentityStore(domain: domain, username: username)
                return true
            }
        }

        return false
    }

    // MARK: - Query

    /// Get all credentials for a domain.
    func getCredentials(for domain: String) -> [(username: String, password: String)] {
        let query: [String: Any] = [
            kSecClass as String: kSecClassInternetPassword,
            kSecAttrServer as String: domain,
            kSecAttrAccessGroup as String: accessGroup,
            kSecReturnAttributes as String: true,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitAll,
        ]

        var result: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &result)

        guard status == errSecSuccess,
              let items = result as? [[String: Any]] else {
            return []
        }

        return items.compactMap { item in
            guard let username = item[kSecAttrAccount as String] as? String,
                  let data = item[kSecValueData as String] as? Data,
                  let password = String(data: data, encoding: .utf8) else {
                return nil
            }
            return (username: username, password: password)
        }
    }

    /// Get all domains that have stored credentials, sorted alphabetically.
    func getAllDomains() -> [String] {
        let query: [String: Any] = [
            kSecClass as String: kSecClassInternetPassword,
            kSecAttrAccessGroup as String: accessGroup,
            kSecReturnAttributes as String: true,
            kSecMatchLimit as String: kSecMatchLimitAll,
        ]

        var result: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &result)

        guard status == errSecSuccess,
              let items = result as? [[String: Any]] else {
            return []
        }

        let domains = items.compactMap { $0[kSecAttrServer as String] as? String }
        return Array(Set(domains)).sorted()
    }

    /// Total number of stored credentials.
    func credentialCount() -> Int {
        let query: [String: Any] = [
            kSecClass as String: kSecClassInternetPassword,
            kSecAttrAccessGroup as String: accessGroup,
            kSecReturnAttributes as String: true,
            kSecMatchLimit as String: kSecMatchLimitAll,
        ]

        var result: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &result)

        guard status == errSecSuccess,
              let items = result as? [[String: Any]] else {
            return 0
        }
        return items.count
    }

    // MARK: - Delete

    /// Delete all credentials in the shared access group.
    @discardableResult
    func deleteAll() -> Bool {
        let query: [String: Any] = [
            kSecClass as String: kSecClassInternetPassword,
            kSecAttrAccessGroup as String: accessGroup,
        ]
        let status = SecItemDelete(query as CFDictionary)

        Task {
            try? await ASCredentialIdentityStore.shared.removeAllCredentialIdentities()
        }

        return status == errSecSuccess || status == errSecItemNotFound
    }

    // MARK: - Identity Store

    /// Update ASCredentialIdentityStore so QuickType bar shows suggestions.
    private func updateIdentityStore(domain: String, username: String) {
        let serviceIdentifier = ASCredentialServiceIdentifier(
            identifier: domain,
            type: .domain
        )
        let identity = ASPasswordCredentialIdentity(
            serviceIdentifier: serviceIdentifier,
            user: username,
            recordIdentifier: "\(domain)/\(username)"
        )
        Task {
            try? await ASCredentialIdentityStore.shared.saveCredentialIdentities([identity])
        }
    }
}
