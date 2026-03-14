import SwiftUI

/// Top header bar showing bot name, initials avatar, and online/offline status.
struct ChatHeaderView: View {
    let botName: String
    let isOnline: Bool
    var onSettings: (() -> Void)? = nil
    var onClear: (() -> Void)? = nil

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 10) {
                // Initials avatar
                Circle()
                    .fill(Color.blue)
                    .frame(width: 32, height: 32)
                    .overlay(
                        Text(String(botName.prefix(1)))
                            .font(.system(size: 14, weight: .semibold))
                            .foregroundStyle(.white)
                    )

                VStack(alignment: .leading, spacing: 1) {
                    Text(botName)
                        .font(.system(size: 16, weight: .semibold))
                        .foregroundStyle(.primary)

                    HStack(spacing: 4) {
                        Circle()
                            .fill(isOnline ? Color.green : Color(.systemGray4))
                            .frame(width: 6, height: 6)
                        Text(isOnline ? "Online" : "Offline")
                            .font(.system(size: 13))
                            .foregroundStyle(.gray)
                    }
                }

                Spacer()

                if let onSettings {
                    Button(action: onSettings) {
                        Image(systemName: "gearshape")
                            .font(.system(size: 15))
                            .foregroundStyle(.secondary)
                    }
                }

                if let onClear {
                    Button(action: onClear) {
                        Image(systemName: "trash")
                            .font(.system(size: 15))
                            .foregroundStyle(.secondary)
                    }
                }
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 12)

            Rectangle()
                .fill(Color(.systemGray5))
                .frame(height: 0.5)
        }
        .background {
            Color(.systemBackground).opacity(0.75)
                .background(.thinMaterial)
                .ignoresSafeArea(edges: .top)
        }
    }
}

#Preview("Online") {
    ChatHeaderView(botName: "ClawBot", isOnline: true)
}

#Preview("Offline") {
    ChatHeaderView(botName: "ClawBot", isOnline: false)
}
