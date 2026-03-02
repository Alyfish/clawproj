import SwiftUI

struct WatchlistDetailView: View {
    let item: WatchlistItem
    let alerts: [MonitoringAlert]

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
                            Text(alert.message)
                                .font(.subheadline)

                            // Data preview
                            if !alert.data.isEmpty {
                                HStack(spacing: 8) {
                                    ForEach(alert.data.sorted(by: { $0.key < $1.key }).prefix(3), id: \.key) { key, value in
                                        Text("\(key): \(value)")
                                            .font(.caption2)
                                            .foregroundStyle(.secondary)
                                            .padding(.horizontal, 6)
                                            .padding(.vertical, 2)
                                            .background(Color(.systemGray6))
                                            .clipShape(Capsule())
                                    }
                                }
                            }

                            Text(relativeTime(alert.timestamp))
                                .font(.caption2)
                                .foregroundStyle(.tertiary)
                        }
                        .padding(.vertical, 4)
                    }
                }
            }
        }
        .navigationTitle(item.type.displayName)
        .navigationBarTitleDisplayMode(.inline)
    }

    private var itemAlerts: [MonitoringAlert] {
        alerts
            .filter { $0.watchlistItemId == item.id }
            .sorted { $0.timestamp > $1.timestamp }
    }

    private func relativeTime(_ iso: String) -> String {
        guard let date = ISO8601DateFormatter().date(from: iso) else { return iso }
        let formatter = RelativeDateTimeFormatter()
        formatter.unitsStyle = .short
        return formatter.localizedString(for: date, relativeTo: Date())
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
