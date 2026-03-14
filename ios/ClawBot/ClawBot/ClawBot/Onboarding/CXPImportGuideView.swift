import SwiftUI

/// Visual step-by-step guide for importing passwords via CXP (iOS 26+).
/// Shows instructions for exporting from the Passwords app into ClawBot.
@available(iOS 26, *)
struct CXPImportGuideView: View {
    let onDone: (Int) -> Void
    let onSkip: () -> Void

    @State private var previousCount: Int
    @State private var noChangeMessage = false

    init(onDone: @escaping (Int) -> Void, onSkip: @escaping () -> Void) {
        self.onDone = onDone
        self.onSkip = onSkip
        self._previousCount = State(initialValue: CredentialStore.shared.credentialCount())
    }

    var body: some View {
        VStack(spacing: 24) {
            Text("Import Your Passwords")
                .font(.title2.bold())
                .padding(.top, 24)

            Text("Export from the Passwords app so ClawBot can log in for you.")
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .padding(.horizontal, 32)

            VStack(alignment: .leading, spacing: 20) {
                stepRow(
                    number: 1,
                    icon: "key.fill",
                    title: "Open the Passwords app"
                )
                stepRow(
                    number: 2,
                    icon: "square.and.arrow.up",
                    title: "Tap \u{2022}\u{2022}\u{2022} → Export Data to Another App"
                )
                stepRow(
                    number: 3,
                    icon: "checkmark.circle",
                    title: "Select ClawBot"
                )
            }
            .padding(.horizontal, 24)
            .padding(.vertical, 16)

            if noChangeMessage {
                Text("No new passwords detected. Try the steps above or skip for now.")
                    .font(.caption)
                    .foregroundStyle(.orange)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 32)
            }

            Spacer()

            VStack(spacing: 12) {
                Button(action: verifyImport) {
                    Text("I've done this")
                        .font(.headline)
                        .frame(maxWidth: .infinity)
                        .padding()
                        .background(Color.accentColor)
                        .foregroundStyle(.white)
                        .clipShape(RoundedRectangle(cornerRadius: 14))
                }

                Button("Skip for now", action: onSkip)
                    .foregroundStyle(.secondary)
            }
            .padding(.horizontal, 24)
            .padding(.bottom, 32)
        }
    }

    // MARK: - Private

    private func stepRow(number: Int, icon: String, title: String) -> some View {
        HStack(spacing: 16) {
            ZStack {
                Circle()
                    .fill(Color.accentColor.opacity(0.12))
                    .frame(width: 44, height: 44)
                Image(systemName: icon)
                    .font(.title3)
                    .foregroundStyle(Color.accentColor)
            }

            Text(title)
                .font(.body)

            Spacer()
        }
    }

    private func verifyImport() {
        let currentCount = CredentialStore.shared.credentialCount()
        let delta = currentCount - previousCount

        if delta > 0 {
            noChangeMessage = false
            onDone(delta)
        } else {
            noChangeMessage = true
        }
    }
}

#Preview {
    if #available(iOS 26, *) {
        CXPImportGuideView(onDone: { _ in }, onSkip: {})
    }
}
