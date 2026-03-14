import SwiftUI

struct ExtensionConfigView: View {
    let credentialCount: Int

    var body: some View {
        VStack(spacing: 20) {
            Image(systemName: "key.fill")
                .font(.system(size: 48))
                .foregroundStyle(.blue)

            Text("ClawBot AutoFill")
                .font(.title2.bold())

            Text("Managed by ClawBot")
                .font(.subheadline)
                .foregroundStyle(.secondary)

            if credentialCount > 0 {
                Text("\(credentialCount) password\(credentialCount == 1 ? "" : "s") stored")
                    .font(.callout)
                    .padding(.horizontal, 16)
                    .padding(.vertical, 8)
                    .background(.fill.tertiary)
                    .clipShape(Capsule())
            } else {
                Text("No passwords stored yet")
                    .font(.callout)
                    .foregroundStyle(.secondary)
            }

            Text("ClawBot saves passwords automatically when logging into websites on your behalf.")
                .font(.caption)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .padding(.horizontal, 40)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}
