import Foundation
import AuthenticationServices

/// Handles credential import from other password managers via the Credential Exchange Protocol.
/// iOS 26+ only — all entry points are @available guarded.
@available(iOS 26, *)
final class CXPImportHandler {

    static let activityType = "com.apple.authentication-services.credential-exchange"

    private let credentialStore: CredentialStore

    init(credentialStore: CredentialStore = .shared) {
        self.credentialStore = credentialStore
    }

    /// Handle an NSUserActivity for credential exchange. Returns the number of imported credentials.
    func handleImport(activity: NSUserActivity) async -> Int {
        guard activity.activityType == Self.activityType else { return 0 }

        guard let userInfo = activity.userInfo,
              let token = userInfo.values.compactMap({ $0 as? UUID }).first
                ?? (userInfo.values.compactMap({ $0 as? String }).compactMap(UUID.init).first) else {
            #if DEBUG
            print("[CXPImportHandler] No UUID token found in userInfo")
            #endif
            return 0
        }

        do {
            let manager = ASCredentialImportManager()
            let exportedData = try await manager.importCredentials(token: token)

            var importCount = 0

            for account in exportedData.accounts {
                for item in account.items {
                    // Extract domains from item scope URLs
                    let domains = item.scope?.urls.compactMap(\.host) ?? []

                    for credential in item.credentials {
                        switch credential {
                        case .basicAuthentication(let auth):
                            guard let username = auth.userName?.value,
                                  let password = auth.password?.value else { continue }

                            if domains.isEmpty {
                                // Fallback: use item title as domain hint
                                if credentialStore.save(
                                    domain: item.title,
                                    username: username,
                                    password: password
                                ) {
                                    importCount += 1
                                }
                            } else {
                                for domain in domains {
                                    if credentialStore.save(
                                        domain: domain,
                                        username: username,
                                        password: password
                                    ) {
                                        importCount += 1
                                    }
                                }
                            }

                        case .totp:
                            // TODO: Store TOTP secrets alongside credentials
                            break

                        default:
                            // Skip passkeys, credit cards, wifi, ssh keys, notes for v1
                            break
                        }
                    }
                }
            }

            #if DEBUG
            print("[CXPImportHandler] Imported \(importCount) credential(s)")
            #endif

            return importCount
        } catch {
            #if DEBUG
            print("[CXPImportHandler] Import failed: \(error)")
            #endif
            return 0
        }
    }
}
