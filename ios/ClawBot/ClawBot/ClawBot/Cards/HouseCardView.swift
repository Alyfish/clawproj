import SwiftUI

struct HouseCardView: View {
    let card: HouseCard
    @State private var showDocs = false
    @Environment(\.openURL) private var openURL

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            // MARK: - Top: Rent + Bedrooms
            HStack(alignment: .firstTextBaseline) {
                Text(card.rent.formatted)
                    .font(.title2)
                    .fontWeight(.bold)
                Spacer()
                Text(card.bedroomLabel)
                    .font(.caption)
                    .fontWeight(.semibold)
                    .foregroundStyle(.white)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 3)
                    .background(.blue)
                    .clipShape(Capsule())
            }

            // MARK: - Address
            Text(card.address)
                .font(.subheadline)
                .foregroundStyle(.secondary)

            // MARK: - Area
            Text(card.area)
                .font(.caption)
                .foregroundStyle(.tertiary)

            // MARK: - Commute Chip
            HStack(spacing: 4) {
                Image(systemName: commuteIcon)
                    .font(.caption2)
                Text("\(card.commute.time) \(card.commute.mode) to \(card.commute.destination)")
                    .font(.caption)
            }
            .foregroundStyle(.secondary)
            .padding(.horizontal, 10)
            .padding(.vertical, 5)
            .background(Color(.systemGray6))
            .clipShape(Capsule())

            // MARK: - Move-in Date
            HStack(spacing: 4) {
                Image(systemName: "calendar")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                Text("Move-in: \(card.moveInDate)")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            // MARK: - Red Flags
            if !card.redFlags.isEmpty {
                VStack(alignment: .leading, spacing: 4) {
                    FlowLayout(spacing: 6) {
                        ForEach(card.redFlags, id: \.self) { flag in
                            HStack(spacing: 4) {
                                Image(systemName: "exclamationmark.triangle.fill")
                                    .font(.caption2)
                                Text(flag)
                                    .font(.caption2)
                            }
                            .foregroundStyle(.red)
                            .padding(.horizontal, 8)
                            .padding(.vertical, 4)
                            .background(Color.red.opacity(0.1))
                            .clipShape(Capsule())
                        }
                    }
                }
            }

            // MARK: - Required Docs (collapsible)
            DisclosureGroup("Required Documents (\(card.requiredDocs.count))", isExpanded: $showDocs) {
                VStack(alignment: .leading, spacing: 4) {
                    ForEach(card.requiredDocs, id: \.self) { doc in
                        HStack(spacing: 6) {
                            Image(systemName: "doc.text")
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                            Text(doc)
                                .font(.caption)
                        }
                    }
                }
                .padding(.top, 4)
            }
            .font(.caption)
            .foregroundStyle(.secondary)

            // MARK: - Lease terms
            Text(card.leaseTerms)
                .font(.caption2)
                .foregroundStyle(.tertiary)

            // MARK: - View Listing Button
            Button(action: {
                if let url = URL(string: card.listingUrl) {
                    openURL(url)
                }
            }) {
                HStack {
                    Image(systemName: "safari")
                    Text("View Listing on \(card.source)")
                }
                .font(.subheadline)
                .fontWeight(.medium)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 10)
                .background(Color.blue.opacity(0.1))
                .foregroundStyle(.blue)
                .clipShape(RoundedRectangle(cornerRadius: 10))
            }
        }
        .padding()
        .background(Color(.systemBackground))
        .clipShape(RoundedRectangle(cornerRadius: 12))
        .shadow(color: .black.opacity(0.08), radius: 8, x: 0, y: 2)
    }

    private var commuteIcon: String {
        switch card.commute.mode.lowercased() {
        case "transit", "bus", "train": return "tram.fill"
        case "driving", "car": return "car.fill"
        case "walking", "walk": return "figure.walk"
        case "biking", "bike", "cycling": return "bicycle"
        default: return "mappin"
        }
    }
}

// MARK: - Previews

#Preview("Clean listing") {
    HouseCardView(card: .mockClean)
        .padding()
}

#Preview("Listing with red flags") {
    HouseCardView(card: .mockRedFlags)
        .padding()
}
