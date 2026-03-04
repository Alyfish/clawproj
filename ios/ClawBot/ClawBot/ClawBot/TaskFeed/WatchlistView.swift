import SwiftUI

struct WatchlistView: View {
    let items: [WatchlistItem]
    let alerts: [MonitoringAlert]
    var onToggleActive: (WatchlistItem, Bool) -> Void = { _, _ in }
    var onSelectItem: (WatchlistItem) -> Void = { _ in }

    var body: some View {
        Group {
            if items.isEmpty {
                emptyState
            } else {
                watchList
            }
        }
        .navigationTitle("Watchlists")
        .navigationBarTitleDisplayMode(.inline)
    }

    private var watchList: some View {
        List {
            // New alerts section
            if !unresolvedAlerts.isEmpty {
                Section("Recent Alerts") {
                    ForEach(unresolvedAlerts.prefix(3)) { alert in
                        AlertCardView(alert: alert)
                            .listRowSeparator(.hidden)
                            .listRowInsets(EdgeInsets(top: 4, leading: 16, bottom: 4, trailing: 16))
                    }
                }
            }

            // Watch items
            Section("Active Watches") {
                ForEach(items) { item in
                    WatchlistRowView(
                        item: item,
                        alertCount: alerts.filter { $0.watchlistItemId == item.id }.count,
                        onToggle: { active in onToggleActive(item, active) },
                        onTap: { onSelectItem(item) }
                    )
                }
            }
        }
        .listStyle(.insetGrouped)
    }

    private var unresolvedAlerts: [MonitoringAlert] {
        alerts.sorted { $0.timestamp > $1.timestamp }
    }

    private var emptyState: some View {
        VStack(spacing: 16) {
            Image(systemName: "eye.slash")
                .font(.system(size: 44))
                .foregroundStyle(.tertiary)
            Text("No active watches")
                .font(.headline)
                .foregroundStyle(.secondary)
            Text("Ask ClawBot to monitor prices, listings, or odds to create a watch.")
                .font(.subheadline)
                .foregroundStyle(.tertiary)
                .multilineTextAlignment(.center)
                .padding(.horizontal, 40)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

/// Single row in the watchlist
struct WatchlistRowView: View {
    let item: WatchlistItem
    let alertCount: Int
    var onToggle: (Bool) -> Void = { _ in }
    var onTap: () -> Void = {}

    @State private var isActive: Bool

    init(item: WatchlistItem, alertCount: Int,
         onToggle: @escaping (Bool) -> Void = { _ in },
         onTap: @escaping () -> Void = {}) {
        self.item = item
        self.alertCount = alertCount
        self.onToggle = onToggle
        self.onTap = onTap
        _isActive = State(initialValue: item.active)
    }

    var body: some View {
        Button(action: { onTap() }) {
            HStack(spacing: 10) {
                // Type icon
                Image(systemName: item.type.iconName)
                    .font(.title3)
                    .foregroundStyle(isActive ? typeColor : .gray)
                    .frame(width: 32)

                VStack(alignment: .leading, spacing: 3) {
                    Text(item.description)
                        .font(.subheadline)
                        .foregroundStyle(.primary)
                        .lineLimit(2)

                    HStack(spacing: 8) {
                        // Type badge
                        Text(item.type.displayName)
                            .font(.caption2)
                            .foregroundStyle(typeColor)
                            .padding(.horizontal, 6)
                            .padding(.vertical, 2)
                            .background(typeColor.opacity(0.12))
                            .clipShape(Capsule())

                        // Interval
                        Text(item.intervalFormatted)
                            .font(.caption2)
                            .foregroundStyle(.tertiary)

                        // Last checked
                        if let lc = item.lastCheckedFormatted {
                            Text("· \(lc)")
                                .font(.caption2)
                                .foregroundStyle(.tertiary)
                        }

                        if alertCount > 0 {
                            Text("· \(alertCount) alerts")
                                .font(.caption2)
                                .foregroundStyle(.orange)
                        }
                    }
                }

                Spacer()

                // Active toggle
                Toggle("", isOn: $isActive)
                    .labelsHidden()
                    .onChange(of: isActive) { _, newVal in
                        onToggle(newVal)
                    }
            }
        }
        .buttonStyle(.plain)
    }

    private var typeColor: Color {
        switch item.type {
        case .priceWatch: .green
        case .newListing: .blue
        case .lineMovement: .purple
        }
    }
}

// MARK: - Previews

#Preview("Watchlist with items") {
    NavigationStack {
        WatchlistView(
            items: [.mockPriceWatch, .mockNewListing, .mockLineMovement],
            alerts: [.mockPriceDrop, .mockNewApt, .mockLineAlert]
        )
    }
}

#Preview("Empty watchlist") {
    NavigationStack {
        WatchlistView(items: [], alerts: [])
    }
}
