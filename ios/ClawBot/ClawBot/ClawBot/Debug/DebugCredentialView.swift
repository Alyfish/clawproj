#if DEBUG
import SwiftUI

struct DebugCredentialView: View {
    @State private var domain = ""
    @State private var username = ""
    @State private var password = ""
    @State private var savedDomains: [String] = []
    @State private var statusMessage = ""

    private let store = CredentialStore.shared

    var body: some View {
        Form {
            Section("Add Credential") {
                TextField("Domain (e.g. amazon.com)", text: $domain)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                TextField("Username / Email / Phone", text: $username)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                SecureField("Password", text: $password)

                Button("Save Credential") {
                    guard !domain.isEmpty, !username.isEmpty, !password.isEmpty else {
                        statusMessage = "All fields required"
                        return
                    }
                    let ok = store.save(domain: domain, username: username, password: password)
                    statusMessage = ok ? "Saved \(domain)" : "Failed to save"
                    if ok {
                        domain = ""
                        username = ""
                        password = ""
                        refreshDomains()
                    }
                }
                .disabled(domain.isEmpty || username.isEmpty || password.isEmpty)

                if !statusMessage.isEmpty {
                    Text(statusMessage)
                        .font(.caption)
                        .foregroundStyle(statusMessage.contains("Failed") ? .red : .green)
                }
            }

            Section("Quick Add") {
                Button("Apple Developer") {
                    domain = "developer.apple.com"
                    username = "alirahimj17@gmail.com"
                    password = "U+n@Vnc3wa^Srpd"
                }
                Button("Amazon") {
                    domain = "amazon.com"
                    username = "7262052442"
                    password = "123fish"
                }
            }

            Section("Stored Credentials (\(store.credentialCount()))") {
                if savedDomains.isEmpty {
                    Text("No credentials saved")
                        .foregroundStyle(.secondary)
                } else {
                    ForEach(savedDomains, id: \.self) { d in
                        let creds = store.getCredentials(for: d)
                        HStack {
                            VStack(alignment: .leading) {
                                Text(d).font(.body)
                                Text("\(creds.count) credential(s)")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                            Spacer()
                            Image(systemName: "checkmark.circle.fill")
                                .foregroundStyle(.green)
                        }
                    }
                }
            }

            Section {
                Button("Delete All Credentials", role: .destructive) {
                    _ = store.deleteAll()
                    refreshDomains()
                    statusMessage = "All credentials deleted"
                }
            }
        }
        .navigationTitle("Test Credentials")
        .onAppear { refreshDomains() }
    }

    private func refreshDomains() {
        savedDomains = store.getAllDomains()
    }
}
#endif
