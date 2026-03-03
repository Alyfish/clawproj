import SwiftUI

// MARK: - LoginCardView

/// Inline chat card shown when the agent needs the user to log in.
struct LoginCardView: View {
    let profile: String
    let domain: String
    let onStart: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Label("Login Required", systemImage: "lock.shield")
                .font(.headline)
                .foregroundStyle(.primary)

            Text("Securely log into \(domain) using the browser. Your credentials stay in the browser — never sent to the agent.")
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)

            HStack {
                Text("Profile: \(profile)")
                    .font(.caption)
                    .foregroundStyle(.tertiary)
                Spacer()
            }

            Button(action: onStart) {
                Label("Start Login", systemImage: "globe")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
            .tint(.orange)
        }
        .padding(16)
        .background(
            RoundedRectangle(cornerRadius: 16)
                .fill(.ultraThinMaterial)
        )
        .overlay(
            RoundedRectangle(cornerRadius: 16)
                .stroke(Color.orange.opacity(0.3), lineWidth: 1)
        )
    }
}
