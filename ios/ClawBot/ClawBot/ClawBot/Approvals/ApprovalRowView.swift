import SwiftUI

// MARK: - PendingApprovalRow

struct PendingApprovalRow: View {
    let request: ApprovalRequest

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: request.action.iconName)
                .font(.title3)
                .foregroundStyle(color(for: request.action.iconColor))
                .frame(width: 28)

            VStack(alignment: .leading, spacing: 6) {
                Text(request.description)
                    .font(.subheadline)
                    .fontWeight(.medium)
                    .lineLimit(2)

                HStack(spacing: 8) {
                    Text(request.action.displayName)
                        .font(.caption2)
                        .fontWeight(.semibold)
                        .foregroundStyle(color(for: request.action.iconColor))
                        .padding(.horizontal, 8)
                        .padding(.vertical, 3)
                        .background(
                            color(for: request.action.iconColor).opacity(0.15),
                            in: Capsule()
                        )

                    Spacer()

                    Text(request.timeAgo)
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                }

                Text("Awaiting")
                    .font(.caption2)
                    .fontWeight(.semibold)
                    .foregroundStyle(.white)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 3)
                    .background(.orange, in: Capsule())
            }
        }
        .padding(.vertical, 4)
    }
}

// MARK: - ResolvedApprovalRow

struct ResolvedApprovalRow: View {
    let resolved: ResolvedApproval

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: resolved.request.action.iconName)
                .font(.title3)
                .foregroundStyle(.secondary)
                .frame(width: 28)

            VStack(alignment: .leading, spacing: 6) {
                Text(resolved.request.description)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)

                HStack(spacing: 8) {
                    DecisionBadge(decision: resolved.response.decision)

                    Spacer()

                    Text(relativeTime(resolved.response.decidedAt))
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                }
            }
        }
        .padding(.vertical, 4)
    }
}

// MARK: - DecisionBadge

struct DecisionBadge: View {
    let decision: ApprovalDecision

    var body: some View {
        Label(decision.displayName, systemImage: iconName)
            .font(.caption2)
            .fontWeight(.semibold)
            .foregroundStyle(badgeColor)
            .padding(.horizontal, 8)
            .padding(.vertical, 3)
            .background(badgeColor.opacity(0.15), in: Capsule())
    }

    private var iconName: String {
        switch decision {
        case .approved: "checkmark"
        case .denied: "xmark"
        }
    }

    private var badgeColor: Color {
        switch decision {
        case .approved: .green
        case .denied: .red
        }
    }
}

// MARK: - Helpers

private func color(for name: String) -> Color {
    switch name {
    case "blue": .blue
    case "green": .green
    case "indigo": .indigo
    case "red": .red
    case "orange": .orange
    default: .primary
    }
}

private func relativeTime(_ iso: String) -> String {
    let formatter = ISO8601DateFormatter()
    guard let date = formatter.date(from: iso) else { return iso }
    let relative = RelativeDateTimeFormatter()
    relative.unitsStyle = .abbreviated
    return relative.localizedString(for: date, relativeTo: Date())
}

// MARK: - Previews

#Preview("Pending — Submit") {
    PendingApprovalRow(request: .mockSubmit)
        .padding()
}

#Preview("Pending — Pay") {
    PendingApprovalRow(request: .mockPay)
        .padding()
}

#Preview("Pending — Delete") {
    PendingApprovalRow(request: .mockDelete)
        .padding()
}

#Preview("Resolved — Approved") {
    ResolvedApprovalRow(resolved: .mockApproved)
        .padding()
}

#Preview("Resolved — Denied") {
    ResolvedApprovalRow(resolved: .mockDenied)
        .padding()
}
