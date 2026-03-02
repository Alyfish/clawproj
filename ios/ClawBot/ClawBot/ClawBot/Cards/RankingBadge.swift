import SwiftUI

// MARK: - BadgeStyle

enum BadgeStyle {
    case bestOverall
    case cheapest
    case fastest
    case bestForPoints
    case custom(Color)

    var color: Color {
        switch self {
        case .bestOverall: return .blue
        case .cheapest: return .green
        case .fastest: return .orange
        case .bestForPoints: return .purple
        case .custom(let color): return color
        }
    }

    /// Auto-maps a ranking label string to a badge style.
    static func from(label: String) -> BadgeStyle {
        switch label.lowercased() {
        case "best overall": return .bestOverall
        case "cheapest": return .cheapest
        case "fastest": return .fastest
        case "best for points": return .bestForPoints
        default: return .custom(.gray)
        }
    }
}

// MARK: - RankingBadge

struct RankingBadge: View {
    let label: String
    let style: BadgeStyle

    /// Auto-maps label to style.
    init(_ label: String) {
        self.label = label
        self.style = BadgeStyle.from(label: label)
    }

    /// Explicit style.
    init(_ label: String, style: BadgeStyle) {
        self.label = label
        self.style = style
    }

    var body: some View {
        Text(label)
            .font(.caption)
            .fontWeight(.semibold)
            .foregroundStyle(.white)
            .padding(.horizontal, 10)
            .padding(.vertical, 4)
            .background(style.color, in: Capsule())
    }
}

// MARK: - Preview

#Preview("All Styles") {
    VStack(spacing: 12) {
        RankingBadge("Best Overall")
        RankingBadge("Cheapest")
        RankingBadge("Fastest")
        RankingBadge("Best for Points")
        RankingBadge("Custom Label", style: .custom(.red))
    }
    .padding()
}
