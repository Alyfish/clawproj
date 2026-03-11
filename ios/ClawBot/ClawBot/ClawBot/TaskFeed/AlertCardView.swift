import SwiftUI

/// Compact alert row — used in WatchlistView and WatchlistDetailView.
struct WatchlistAlertRow: View {
    let alert: WatchlistAlert
    var onTap: (() -> Void)?

    var body: some View {
        Button(action: { onTap?() }) {
            HStack(spacing: 12) {
                // Alert icon
                Image(systemName: alert.alertIcon)
                    .foregroundColor(alert.alertColor)
                    .font(.title3)
                    .frame(width: 32, height: 32)

                VStack(alignment: .leading, spacing: 4) {
                    // Title + unread dot
                    HStack {
                        Text(alert.title)
                            .font(.subheadline.bold())
                            .lineLimit(1)
                        if !alert.isRead {
                            Circle()
                                .fill(.blue)
                                .frame(width: 8, height: 8)
                        }
                    }

                    // Message
                    Text(alert.message)
                        .font(.caption)
                        .foregroundColor(.secondary)
                        .lineLimit(2)

                    // Source + timestamp
                    HStack {
                        Text(alert.source.replacingOccurrences(of: "_", with: " ").capitalized)
                            .font(.caption2)
                            .foregroundColor(.secondary)
                        Spacer()
                        Text(alert.relativeTime)
                            .font(.caption2)
                            .foregroundColor(.secondary)
                    }
                }

                // Value change (if available)
                if alert.currentValue != nil || alert.previousValue != nil {
                    VStack(alignment: .trailing, spacing: 2) {
                        if let current = alert.currentValue {
                            Text(current)
                                .font(.subheadline.bold())
                                .foregroundColor(alert.alertColor)
                        }
                        if let previous = alert.previousValue {
                            Text(previous)
                                .font(.caption2)
                                .foregroundColor(.secondary)
                                .strikethrough()
                        }
                    }
                }
            }
            .padding(12)
            .background(Color(.systemBackground))
            .clipShape(RoundedRectangle(cornerRadius: 10))
            .shadow(color: .black.opacity(0.06), radius: 4, x: 0, y: 1)
            .opacity(alert.isRead ? 0.7 : 1.0)
        }
        .buttonStyle(.plain)
    }
}

#Preview("Price drop (unread)") {
    WatchlistAlertRow(alert: .mockPriceDrop)
        .padding()
}

#Preview("New listing (unread)") {
    WatchlistAlertRow(alert: .mockNewApt)
        .padding()
}

#Preview("Line movement (read)") {
    WatchlistAlertRow(alert: {
        var a = WatchlistAlert.mockLineAlert
        a.isRead = true
        return a
    }())
    .padding()
}
