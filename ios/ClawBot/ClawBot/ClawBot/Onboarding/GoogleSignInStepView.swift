import SwiftUI

/// Onboarding step for connecting a Google account via OAuth.
/// Skippable — user can add Google later from Settings.
struct GoogleSignInStepView: View {
    let onDone: (String?) -> Void  // connected email or nil
    let onSkip: () -> Void

    @State private var isAuthenticating = false
    @State private var connectedEmail: String?
    @State private var errorMessage: String?

    private let oauthManager = GoogleOAuthManager.shared

    private let scopeDescriptions: [(icon: String, label: String)] = [
        ("envelope", "Email (Gmail)"),
        ("folder", "Files (Drive)"),
        ("doc.text", "Documents (Docs)"),
        ("tablecells", "Spreadsheets (Sheets)"),
        ("calendar", "Calendar"),
        ("rectangle.on.rectangle", "Presentations (Slides)"),
    ]

    var body: some View {
        VStack(spacing: 24) {
            Spacer()

            if let email = connectedEmail {
                successView(email: email)
            } else {
                connectView
            }

            Spacer()

            buttonsView
                .padding(.horizontal, 24)
                .padding(.bottom, 32)
        }
    }

    // MARK: - Connect View

    private var connectView: some View {
        VStack(spacing: 20) {
            Image(systemName: "person.badge.key")
                .font(.system(size: 48))
                .foregroundStyle(Color.accentColor)

            Text("Connect Google Account")
                .font(.title2.bold())

            Text("ClawBot needs access to your Google account to manage emails, files, documents, spreadsheets, calendar, and presentations on your behalf.")
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .padding(.horizontal, 32)

            VStack(alignment: .leading, spacing: 10) {
                ForEach(scopeDescriptions, id: \.label) { scope in
                    HStack(spacing: 12) {
                        Image(systemName: scope.icon)
                            .font(.system(size: 14))
                            .foregroundStyle(Color.accentColor)
                            .frame(width: 20)
                        Text(scope.label)
                            .font(.subheadline)
                            .foregroundStyle(.primary)
                    }
                }
            }
            .padding(.horizontal, 40)

            if let errorMessage {
                Text(errorMessage)
                    .font(.caption)
                    .foregroundStyle(.red)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 32)
            }
        }
    }

    // MARK: - Success View

    private func successView(email: String) -> some View {
        VStack(spacing: 20) {
            Image(systemName: "checkmark.circle.fill")
                .font(.system(size: 56))
                .foregroundStyle(.green)

            Text("Google Connected")
                .font(.title2.bold())

            Text("Connected as \(email)")
                .font(.subheadline)
                .foregroundStyle(.secondary)
        }
    }

    // MARK: - Buttons

    private var buttonsView: some View {
        VStack(spacing: 12) {
            if let email = connectedEmail {
                Button {
                    onDone(email)
                } label: {
                    Text("Continue")
                        .font(.headline)
                        .frame(maxWidth: .infinity)
                        .padding()
                        .background(Color.accentColor)
                        .foregroundStyle(.white)
                        .clipShape(RoundedRectangle(cornerRadius: 14))
                }
            } else {
                Button {
                    startAuth()
                } label: {
                    HStack {
                        if isAuthenticating {
                            ProgressView()
                                .tint(.white)
                        }
                        Text(isAuthenticating ? "Connecting..." : "Connect Google Account")
                    }
                    .font(.headline)
                    .frame(maxWidth: .infinity)
                    .padding()
                    .background(isAuthenticating ? Color.gray : Color.accentColor)
                    .foregroundStyle(.white)
                    .clipShape(RoundedRectangle(cornerRadius: 14))
                }
                .disabled(isAuthenticating)

                Button("Skip for now") {
                    onSkip()
                }
                .foregroundStyle(.secondary)
            }
        }
    }

    // MARK: - Auth

    private func startAuth() {
        isAuthenticating = true
        errorMessage = nil

        Task {
            defer { isAuthenticating = false }

            do {
                try await oauthManager.authenticate()
                connectedEmail = oauthManager.userEmail
            } catch let error as GoogleOAuthError {
                switch error {
                case .authFailed(let reason) where reason == "cancelled":
                    // User cancelled — treat as skip, no error shown
                    break
                default:
                    errorMessage = "Could not connect. Please try again."
                    #if DEBUG
                    print("[GoogleSignIn] error: \(error.localizedDescription)")
                    #endif
                }
            } catch {
                errorMessage = "Could not connect. Please try again."
                #if DEBUG
                print("[GoogleSignIn] error: \(error.localizedDescription)")
                #endif
            }
        }
    }
}
