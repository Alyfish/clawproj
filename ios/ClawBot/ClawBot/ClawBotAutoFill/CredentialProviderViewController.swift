import AuthenticationServices
import SwiftUI

class CredentialProviderViewController: ASCredentialProviderViewController {

    private let store = CredentialStore.shared

    // MARK: - Fast Path (no UI)

    override func provideCredentialWithoutUserInteraction(
        for credentialIdentity: ASPasswordCredentialIdentity
    ) {
        let domain = credentialIdentity.serviceIdentifier.identifier
        let requestedUser = credentialIdentity.user

        let credentials = store.getCredentials(for: domain)

        if let match = credentials.first(where: { $0.username == requestedUser }) {
            let credential = ASPasswordCredential(
                user: match.username,
                password: match.password
            )
            extensionContext.completeRequest(withSelectedCredential: credential)
            return
        }

        // No exact match — require user interaction to pick
        extensionContext.cancelRequest(
            withError: NSError(
                domain: ASExtensionErrorDomain,
                code: ASExtensionError.userInteractionRequired.rawValue
            )
        )
    }

    // MARK: - Credential List (with UI)

    override func prepareCredentialList(
        for serviceIdentifiers: [ASCredentialServiceIdentifier]
    ) {
        let domains = serviceIdentifiers.map(\.identifier)

        // Gather all matching credentials for the requested domains
        var matches: [(domain: String, username: String, password: String)] = []
        for domain in domains {
            let creds = store.getCredentials(for: domain)
            for cred in creds {
                matches.append((domain: domain, username: cred.username, password: cred.password))
            }
        }

        // If no matches for specific domains, show all stored credentials
        if matches.isEmpty {
            let allDomains = store.getAllDomains()
            for domain in allDomains {
                let creds = store.getCredentials(for: domain)
                for cred in creds {
                    matches.append((domain: domain, username: cred.username, password: cred.password))
                }
            }
        }

        let listView = CredentialListView(
            credentials: matches.map { CredentialListItem(domain: $0.domain, username: $0.username) },
            onSelect: { [weak self] item in
                guard let self else { return }
                let creds = self.store.getCredentials(for: item.domain)
                if let match = creds.first(where: { $0.username == item.username }) {
                    let credential = ASPasswordCredential(
                        user: match.username,
                        password: match.password
                    )
                    self.extensionContext.completeRequest(withSelectedCredential: credential)
                }
            },
            onCancel: { [weak self] in
                self?.extensionContext.cancelRequest(
                    withError: NSError(
                        domain: ASExtensionErrorDomain,
                        code: ASExtensionError.userCanceled.rawValue
                    )
                )
            }
        )

        let host = UIHostingController(rootView: listView)
        addChild(host)
        host.view.frame = view.bounds
        host.view.autoresizingMask = [.flexibleWidth, .flexibleHeight]
        view.addSubview(host.view)
        host.didMove(toParent: self)
    }

    // MARK: - Extension Configuration

    override func prepareInterfaceForExtensionConfiguration() {
        let configView = ExtensionConfigView(credentialCount: store.credentialCount())

        let host = UIHostingController(rootView: configView)
        addChild(host)
        host.view.frame = view.bounds
        host.view.autoresizingMask = [.flexibleWidth, .flexibleHeight]
        view.addSubview(host.view)
        host.didMove(toParent: self)
    }
}
