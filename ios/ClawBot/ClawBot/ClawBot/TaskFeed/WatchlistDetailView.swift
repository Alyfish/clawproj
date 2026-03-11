import SwiftUI

struct WatchlistDetailView: View {
    let item: WatchlistItem
    let alerts: [WatchlistAlert]
    var onMarkAsRead: ((String) -> Void)?

    var body: some View {
        List {
            // Info section
            Section("Details") {
                LabeledContent("Type", value: item.type.displayName)
                LabeledContent("Check Interval", value: item.intervalFormatted)
                if let lc = item.lastCheckedFormatted {
                    LabeledContent("Last Checked", value: lc)
                }
                LabeledContent("Status", value: item.active ? "Active" : "Paused")
            }

            // Filters section
            if !item.filters.isEmpty {
                Section("Filters") {
                    ForEach(item.filters.sorted(by: { $0.key < $1.key }), id: \.key) { key, value in
                        LabeledContent(key.capitalized, value: value)
                    }
                }
            }

            // Alerts section
            Section("Alerts (\(itemAlerts.count))") {
                if itemAlerts.isEmpty {
                    Text("No alerts yet")
                        .font(.subheadline)
                        .foregroundStyle(.tertiary)
                } else {
                    ForEach(itemAlerts) { alert in
                        VStack(alignment: .leading, spacing: 4) {
                            HStack {
                                Image(systemName: alert.alertIcon)
                                    .foregroundColor(alert.alertColor)
                                    .font(.caption)
                                Text(alert.message)
                                    .font(.subheadline)
                                if !alert.isRead {
                                    Spacer()
                                    Circle()
                                        .fill(.blue)
                                        .frame(width: 6, height: 6)
                                }
                            }

                            // Value change
                            if let prev = alert.previousValue, let curr = alert.currentValue {
                                HStack(spacing: 8) {
                                    Text(prev)
                                        .font(.caption2)
                                        .foregroundStyle(.secondary)
                                        .strikethrough()
                                    Image(systemName: "arrow.right")
                                        .font(.caption2)
                                        .foregroundStyle(.tertiary)
                                    Text(curr)
                                        .font(.caption2)
                                        .fontWeight(.semibold)
                                        .foregroundColor(alert.alertColor)
                                }
                            }

                            Text(alert.relativeTime)
                                .font(.caption2)
                                .foregroundStyle(.tertiary)
                        }
                        .padding(.vertical, 4)
                        .opacity(alert.isRead ? 0.7 : 1.0)
                        .swipeActions(edge: .trailing) {
                            if !alert.isRead {
                                Button("Read") {
                                    onMarkAsRead?(alert.id)
                                }
                                .tint(.blue)
                            }
                        }
                    }
                }
            }
        }
        .navigationTitle(item.type.displayName)
        .navigationBarTitleDisplayMode(.inline)
    }

    private var itemAlerts: [WatchlistAlert] {
        alerts
            .filter { $0.watchId == item.id }
            .sorted { $0.timestamp > $1.timestamp }
    }
}

#Preview("Price watch detail with alerts") {
    NavigationStack {
        WatchlistDetailView(
            item: .mockPriceWatch,
            alerts: [.mockPriceDrop]
        )
    }
}

#Preview("New listing — no alerts") {
    NavigationStack {
        WatchlistDetailView(
            item: .mockNewListing,
            alerts: []
        )
    }
}
