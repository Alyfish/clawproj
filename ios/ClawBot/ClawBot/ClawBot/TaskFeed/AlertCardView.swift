import SwiftUI

/// Compact alert display — shown in watchlist detail and as standalone notification-style card.
struct AlertCardView: View {
    let alert: MonitoringAlert
    var onTap: (() -> Void)?

    var body: some View {
        Button(action: { onTap?() }) {
            HStack(spacing: 10) {
                // Alert icon
                Image(systemName: alertIcon)
                    .font(.title3)
                    .foregroundStyle(alertColor)
                    .frame(width: 32, height: 32)

                VStack(alignment: .leading, spacing: 3) {
                    Text(alert.message)
                        .font(.subheadline)
                        .foregroundStyle(.primary)
                        .lineLimit(2)
                        .multilineTextAlignment(.leading)

                    Text(relativeTime(alert.timestamp))
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                }

                Spacer(minLength: 0)

                Image(systemName: "chevron.right")
                    .font(.caption)
                    .foregroundStyle(.tertiary)
            }
            .padding(12)
            .background(Color(.systemBackground))
            .clipShape(RoundedRectangle(cornerRadius: 10))
            .shadow(color: .black.opacity(0.06), radius: 4, x: 0, y: 1)
        }
        .buttonStyle(.plain)
    }

    private var alertIcon: String {
        if alert.message.lowercased().contains("price") { return "arrow.down.circle.fill" }
        if alert.message.lowercased().contains("listing") || alert.message.lowercased().contains("new") { return "house.badge.plus" }
        if alert.message.lowercased().contains("line") || alert.message.lowercased().contains("moved") { return "chart.line.uptrend.xyaxis" }
        return "bell.badge.fill"
    }

    private var alertColor: Color {
        if alert.message.lowercased().contains("drop") || alert.message.lowercased().contains("favor") { return .green }
        if alert.message.lowercased().contains("new") { return .blue }
        return .orange
    }

    private func relativeTime(_ iso: String) -> String {
        guard let date = ISO8601DateFormatter().date(from: iso) else { return iso }
        let formatter = RelativeDateTimeFormatter()
        formatter.unitsStyle = .short
        return formatter.localizedString(for: date, relativeTo: Date())
    }
}

#Preview("Price drop alert") {
    AlertCardView(alert: .mockPriceDrop)
        .padding()
}

#Preview("New listing alert") {
    AlertCardView(alert: .mockNewApt)
        .padding()
}

#Preview("Line movement alert") {
    AlertCardView(alert: .mockLineAlert)
        .padding()
}
