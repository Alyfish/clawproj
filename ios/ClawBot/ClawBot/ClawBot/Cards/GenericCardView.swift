import SwiftUI

// MARK: - GenericCardView
// Renders a BaseCard with dynamic metadata layout.
// Handles any card type that doesn't have a specialized view.

struct GenericCardView: View {
    let card: BaseCard
    var onAction: CardActionHandler? = nil
    @State private var loadingAction: String?
    @Environment(\.openURL) private var openURL

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            headerSection
            rankingSection
            metadataSection
            actionsSection
            sourceFooter
        }
        .padding()
        .background(Color(.systemBackground))
        .clipShape(RoundedRectangle(cornerRadius: 12))
        .shadow(color: .black.opacity(0.08), radius: 8, x: 0, y: 2)
    }

    // MARK: - Header

    private var headerSection: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(card.title)
                    .font(.title2)
                    .fontWeight(.bold)
                Spacer()
                Text(card.type.replacingOccurrences(of: "_", with: " ").capitalized)
                    .font(.caption2)
                    .fontWeight(.semibold)
                    .foregroundStyle(.secondary)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 3)
                    .background(Color(.systemGray5), in: Capsule())
            }

            if let subtitle = card.subtitle {
                Text(subtitle)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
        }
    }

    // MARK: - Ranking Badge

    @ViewBuilder
    private var rankingSection: some View {
        if let ranking = card.ranking {
            VStack(alignment: .leading, spacing: 4) {
                RankingBadge(ranking.label)
                Text(ranking.reason)
                    .font(.caption)
                    .foregroundStyle(.tertiary)
                    .italic()
            }
        }
    }

    // MARK: - Metadata

    @ViewBuilder
    private var metadataSection: some View {
        let keys = card.visibleMetadataKeys
        if !keys.isEmpty {
            VStack(alignment: .leading, spacing: 8) {
                ForEach(keys, id: \.self) { key in
                    if let value = card.metadata[key] {
                        metadataRow(key: key, value: AnyCodableValue.from(value))
                    }
                }
            }
        }
    }

    @ViewBuilder
    private func metadataRow(key: String, value: AnyCodableValue, depth: Int = 0) -> some View {
        let formattedKey = BaseCard.formatKey(key)
        let isMoney = BaseCard.isMoneyKey(key)
        let isWarning = BaseCard.isWarningKey(key)

        HStack(alignment: .top, spacing: 8) {
            Text(formattedKey)
                .font(.caption)
                .foregroundStyle(.secondary)
                .frame(width: depth == 0 ? 100 : 80, alignment: .leading)

            metadataValueView(value, key: key, depth: depth)
                .font(.caption)
                .fontWeight(isMoney || isWarning ? .semibold : .regular)
                .foregroundStyle(isMoney ? .green : isWarning ? .red : .primary)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    @ViewBuilder
    private func metadataValueView(_ value: AnyCodableValue, key: String, depth: Int) -> some View {
        switch value {
        case .string(let s):
            Text(s)

        case .int(let i):
            Text(formatNumber(Double(i)))

        case .double(let d):
            Text(formatNumber(d))

        case .bool(let b):
            HStack(spacing: 4) {
                Image(systemName: b ? "checkmark.circle.fill" : "xmark.circle")
                    .foregroundStyle(b ? .green : .red)
                Text(b ? "Yes" : "No")
            }

        case .array(let items):
            FlowLayout(spacing: 4) {
                ForEach(Array(items.enumerated()), id: \.offset) { _, item in
                    Text(item.displayString)
                        .font(.caption2)
                        .padding(.horizontal, 8)
                        .padding(.vertical, 3)
                        .background(Color(.systemGray6))
                        .clipShape(Capsule())
                }
            }

        case .dictionary(let dict) where depth < 2:
            VStack(alignment: .leading, spacing: 4) {
                ForEach(dict.keys.sorted(), id: \.self) { subKey in
                    if let subValue = dict[subKey] {
                        AnyView(metadataRow(key: subKey, value: subValue, depth: depth + 1))
                    }
                }
            }
            .padding(.leading, 8)

        case .dictionary:
            Text("{...}")
                .foregroundStyle(.tertiary)

        case .null:
            Text("—")
                .foregroundStyle(.tertiary)
        }
    }

    private func formatNumber(_ value: Double) -> String {
        if value >= 1_000_000_000 {
            return String(format: "%.1fB", value / 1_000_000_000)
        } else if value >= 1_000_000 {
            return String(format: "%.1fM", value / 1_000_000)
        }
        let formatter = NumberFormatter()
        formatter.numberStyle = .decimal
        formatter.maximumFractionDigits = value == value.rounded() ? 0 : 2
        return formatter.string(from: NSNumber(value: value)) ?? "\(value)"
    }

    // MARK: - Actions

    @ViewBuilder
    private var actionsSection: some View {
        if let actions = card.actions, !actions.isEmpty {
            VStack(spacing: 8) {
                ForEach(actions) { action in
                    actionButton(action)
                }
            }
        }
    }

    @ViewBuilder
    private func actionButton(_ action: CardAction) -> some View {
        switch action.type {
        case .link:
            Button {
                if let urlString = action.url, let url = URL(string: urlString) {
                    openURL(url)
                }
            } label: {
                HStack(spacing: 6) {
                    Image(systemName: "arrow.up.right.square")
                    Text(action.label)
                }
                .font(.subheadline)
                .foregroundStyle(.blue)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 10)
                .background(Color.blue.opacity(0.08))
                .clipShape(RoundedRectangle(cornerRadius: 10))
            }

        case .approve:
            Button {
                loadingAction = action.id
                onAction?(action.approvalAction ?? "approve")
                Task {
                    try? await Task.sleep(nanoseconds: 2_000_000_000)
                    loadingAction = nil
                }
            } label: {
                HStack(spacing: 6) {
                    Image(systemName: "checkmark.shield")
                    Text(action.label)
                }
                .font(.subheadline)
                .fontWeight(.medium)
                .foregroundStyle(.white)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 10)
                .background(.green)
                .clipShape(RoundedRectangle(cornerRadius: 10))
            }
            .disabled(loadingAction != nil)

        case .dismiss:
            Button {
                loadingAction = action.id
                onAction?("dismiss")
                Task {
                    try? await Task.sleep(nanoseconds: 2_000_000_000)
                    loadingAction = nil
                }
            } label: {
                HStack(spacing: 6) {
                    Image(systemName: "xmark")
                    Text(action.label)
                }
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 10)
            }
            .disabled(loadingAction != nil)

        case .copy:
            Button {
                UIPasteboard.general.string = card.title
            } label: {
                HStack(spacing: 6) {
                    Image(systemName: "doc.on.doc")
                    Text(action.label)
                }
                .font(.subheadline)
                .foregroundStyle(.blue)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 10)
                .background(Color.blue.opacity(0.08))
                .clipShape(RoundedRectangle(cornerRadius: 10))
            }

        case .custom:
            Button {
                loadingAction = action.id
                onAction?(action.id)
                Task {
                    try? await Task.sleep(nanoseconds: 2_000_000_000)
                    loadingAction = nil
                }
            } label: {
                HStack(spacing: 6) {
                    Image(systemName: "gear")
                    Text(action.label)
                }
                .font(.subheadline)
                .foregroundStyle(.primary)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 10)
                .overlay(
                    RoundedRectangle(cornerRadius: 10)
                        .stroke(Color(.systemGray4), lineWidth: 1)
                )
            }
            .disabled(loadingAction != nil)
        }
    }

    // MARK: - Source Footer

    @ViewBuilder
    private var sourceFooter: some View {
        if let source = card.source {
            Text("Powered by \(source)")
                .font(.caption2)
                .foregroundStyle(.secondary)
        }
    }
}

// MARK: - Previews

#Preview("Shopify Order — rich metadata") {
    ScrollView {
        GenericCardView(card: .mockShopifyOrder)
            .padding()
    }
    .background(Color(.systemGroupedBackground))
}

#Preview("Crypto Price — with ranking + actions") {
    ScrollView {
        GenericCardView(card: .mockCryptoPrice)
            .padding()
    }
    .background(Color(.systemGroupedBackground))
}

#Preview("Minimal — empty metadata") {
    GenericCardView(card: .mockMinimal)
        .padding()
}

#Preview("All generic cards") {
    ScrollView {
        VStack(spacing: 16) {
            GenericCardView(card: .mockShopifyOrder)
            GenericCardView(card: .mockCryptoPrice)
            GenericCardView(card: .mockMinimal)
        }
        .padding()
    }
    .background(Color(.systemGroupedBackground))
}
