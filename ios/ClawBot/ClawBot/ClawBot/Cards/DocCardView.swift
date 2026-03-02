import SwiftUI

struct DocCardView: View {
    let card: DocCard
    @Environment(\.openURL) private var openURL

    var body: some View {
        HStack(spacing: 12) {
            // Doc type icon
            Image(systemName: card.iconName)
                .font(.title2)
                .foregroundStyle(iconColor)
                .frame(width: 44, height: 44)
                .background(iconColor.opacity(0.12))
                .clipShape(RoundedRectangle(cornerRadius: 10))

            // Content
            VStack(alignment: .leading, spacing: 4) {
                Text(card.title)
                    .font(.subheadline)
                    .fontWeight(.medium)
                    .lineLimit(2)

                Text(card.previewText)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(3)

                if let modified = card.lastModified {
                    Text("Modified \(formattedDate(modified))")
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                }
            }

            Spacer(minLength: 0)

            // Open button
            Button(action: {
                if let url = URL(string: card.url) {
                    openURL(url)
                }
            }) {
                Image(systemName: "arrow.up.right.square")
                    .font(.title3)
                    .foregroundStyle(.blue)
            }
        }
        .padding()
        .background(Color(.systemBackground))
        .clipShape(RoundedRectangle(cornerRadius: 12))
        .shadow(color: .black.opacity(0.08), radius: 8, x: 0, y: 2)
    }

    private var iconColor: Color {
        switch card.iconColor {
        case "blue": .blue
        case "green": .green
        case "purple": .purple
        case "orange": .orange
        default: .gray
        }
    }

    private func formattedDate(_ iso: String) -> String {
        let formatter = ISO8601DateFormatter()
        guard let date = formatter.date(from: iso) else { return iso }
        let relative = RelativeDateTimeFormatter()
        relative.unitsStyle = .short
        return relative.localizedString(for: date, relativeTo: Date())
    }
}

// MARK: - Previews

#Preview("Document card") {
    DocCardView(card: .mockDocument)
        .padding()
}

#Preview("Spreadsheet card") {
    DocCardView(card: .mockSpreadsheet)
        .padding()
}

#Preview("Both cards") {
    VStack(spacing: 12) {
        DocCardView(card: .mockDocument)
        DocCardView(card: .mockSpreadsheet)
    }
    .padding()
}
