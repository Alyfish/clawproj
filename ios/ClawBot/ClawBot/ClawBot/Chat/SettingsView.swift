import SwiftUI

/// Settings sheet accessible from the chat header gear icon.
struct SettingsView: View {
    @Environment(\.dismiss) private var dismiss

    var onClearChat: (() -> Void)?

    @State private var googleEmail: String?
    @State private var isAuthenticating = false
    @State private var showDisconnectConfirmation = false
    @State private var errorMessage: String?

    private let oauthManager = GoogleOAuthManager.shared

    var body: some View {
        NavigationStack {
            Form {
                googleAccountSection
                chatSection
                aboutSection
            }
            .navigationTitle("Settings")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") { dismiss() }
                }
            }
            .onAppear {
                googleEmail = oauthManager.userEmail
            }
        }
    }

    // MARK: - Google Account Section

    private var googleAccountSection: some View {
        Section {
            if let email = googleEmail {
                HStack {
                    Image(systemName: "checkmark.circle.fill")
                        .foregroundStyle(.green)
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Google Account")
                            .font(.subheadline.bold())
                        Text(email)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                }

                Button("Disconnect Google Account", role: .destructive) {
                    showDisconnectConfirmation = true
                }
                .confirmationDialog(
                    "Disconnect Google Account?",
                    isPresented: $showDisconnectConfirmation,
                    titleVisibility: .visible
                ) {
                    Button("Disconnect", role: .destructive) {
                        oauthManager.signOut()
                        googleEmail = nil
                    }
                    Button("Cancel", role: .cancel) {}
                } message: {
                    Text("ClawBot will no longer be able to access your Google services until you reconnect.")
                }
            } else {
                HStack {
                    Image(systemName: "person.badge.key")
                        .foregroundStyle(.secondary)
                    Text("Google Account")
                        .font(.subheadline.bold())
                    Spacer()
                    Text("Not connected")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                Button {
                    connectGoogle()
                } label: {
                    HStack {
                        if isAuthenticating {
                            ProgressView()
                                .controlSize(.small)
                        }
                        Text(isAuthenticating ? "Connecting..." : "Connect Google Account")
                    }
                }
                .disabled(isAuthenticating)

                if let errorMessage {
                    Text(errorMessage)
                        .font(.caption)
                        .foregroundStyle(.red)
                }
            }
        } header: {
            Text("Google Workspace")
        } footer: {
            Text("Connect your Google account to let ClawBot manage emails, files, documents, spreadsheets, calendar, and presentations.")
        }
    }

    // MARK: - Chat Section

    private var chatSection: some View {
        Section("Chat") {
            if let onClearChat {
                Button("Clear Conversation", role: .destructive) {
                    onClearChat()
                    dismiss()
                }
            }
        }
    }

    // MARK: - About Section

    private var aboutSection: some View {
        Section("About") {
            HStack {
                Text("Version")
                Spacer()
                Text(Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "1.0")
                    .foregroundStyle(.secondary)
            }
        }
    }

    // MARK: - Actions

    private func connectGoogle() {
        isAuthenticating = true
        errorMessage = nil

        Task {
            defer { isAuthenticating = false }

            do {
                try await oauthManager.authenticate()
                googleEmail = oauthManager.userEmail
            } catch let error as GoogleOAuthError {
                switch error {
                case .authFailed(let reason) where reason == "cancelled":
                    break
                default:
                    errorMessage = "Could not connect. Please try again."
                }
            } catch {
                errorMessage = "Could not connect. Please try again."
            }
        }
    }
}
