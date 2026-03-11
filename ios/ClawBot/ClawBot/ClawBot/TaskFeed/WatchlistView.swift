import SwiftUI

struct WatchlistView: View {
    let items: [WatchlistItem]
    let alerts: [WatchlistAlert]
    var onToggleActive: (WatchlistItem, Bool) -> Void = { _, _ in }
    var onSelectItem: (WatchlistItem) -> Void = { _ in }
    var onMarkAsRead: ((String) -> Void)?
    var onMarkAllAsRead: (() -> Void)?
    var onAlertTap: ((WatchlistAlert) -> Void)?

    var body: some View {
        Group {
            if items.isEmpty && alerts.isEmpty {
                emptyState
            } else {
                watchList
            }
        }
        .navigationTitle("Watchlists")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            if unreadCount > 0 {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Mark All Read") {
                        onMarkAllAsRead?()
                    }
                    .font(.caption)
                }
            }
        }
    }

    private var watchList: some View {
        List {
            // Alerts section
            if !sortedAlerts.isEmpty {
                Section(alertsSectionHeader) {
                    ForEach(sortedAlerts) { alert in
                        WatchlistAlertRow(alert: alert) {
                            onMarkAsRead?(alert.id)
                            onAlertTap?(alert)
                        }
                        .listRowSeparator(.hidden)
                        .listRowInsets(EdgeInsets(top: 4, leading: 16, bottom: 4, trailing: 16))
                    }
                }
            }

            // Watch items
            if !items.isEmpty {
                Section("Active Watches") {
                    ForEach(items) { item in
                        WatchlistRowView(
                            item: item,
                            alertCount: alerts.filter { $0.watchId == item.id }.count,
                            onToggle: { active in onToggleActive(item, active) },
                            onTap: { onSelectItem(item) }
                        )
                    }
                }
            }
        }
        .listStyle(.insetGrouped)
    }

    private var sortedAlerts: [WatchlistAlert] {
        alerts.sorted { $0.timestamp > $1.timestamp }
    }

    private var unreadCount: Int {
        alerts.filter { !$0.isRead }.count
    }

    private var alertsSectionHeader: String {
        if unreadCount > 0 {
            return "Recent Alerts (\(unreadCount) unread)"
        }
        return "Recent Alerts"
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
