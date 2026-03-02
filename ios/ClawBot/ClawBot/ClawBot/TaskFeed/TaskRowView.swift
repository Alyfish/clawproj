import SwiftUI

// MARK: - StatusBadge

struct StatusBadge: View {
    let status: TaskStatus

    var body: some View {
        Text(status.displayName)
            .font(.caption2)
            .fontWeight(.semibold)
            .foregroundStyle(.white)
            .padding(.horizontal, 8)
            .padding(.vertical, 3)
            .background(badgeColor, in: Capsule())
    }

    private var badgeColor: Color {
        switch status {
        case .planning, .searching, .executing:
            return .blue
        case .waitingInput, .waitingApproval:
            return .orange
        case .monitoring:
            return .purple
        case .completed:
            return .green
        case .stopped:
            return .gray
        }
    }
}

// MARK: - TaskRowView

struct TaskRowView: View {
    let task: AgentTask

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            // Status dot
            Circle()
                .fill(statusDotColor)
                .frame(width: 10, height: 10)
                .padding(.top, 5)

            VStack(alignment: .leading, spacing: 6) {
                // Goal text
                Text(task.goal)
                    .font(.subheadline)
                    .fontWeight(.medium)
                    .lineLimit(2)

                // Status badge + card count + timestamp
                HStack(spacing: 8) {
                    StatusBadge(status: task.status)

                    if !task.cardIds.isEmpty {
                        Label("\(task.cardIds.count)", systemImage: "rectangle.stack")
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                    }

                    Spacer()

                    Text(relativeTime(task.updatedAt))
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                }

                // Progress bar for active tasks
                if task.status.isActive {
                    ProgressView()
                        .progressViewStyle(.linear)
                        .tint(progressTint)
                }
            }
        }
        .padding(.vertical, 4)
    }

    // MARK: - Helpers

    private var statusDotColor: Color {
        switch task.status {
        case .planning, .searching, .executing:
            return .blue
        case .waitingInput, .waitingApproval:
            return .orange
        case .monitoring:
            return .purple
        case .completed:
            return .green
        case .stopped:
            return .gray
        }
    }

    private var progressTint: Color {
        switch task.status {
        case .waitingInput, .waitingApproval: return .orange
        case .monitoring: return .purple
        default: return .blue
        }
    }
}

// MARK: - Relative Time Helper

private func relativeTime(_ iso: String) -> String {
    let formatter = ISO8601DateFormatter()
    guard let date = formatter.date(from: iso) else { return iso }
    let relative = RelativeDateTimeFormatter()
    relative.unitsStyle = .abbreviated
    return relative.localizedString(for: date, relativeTo: Date())
}

// MARK: - Previews

#Preview("Completed") {
    TaskRowView(task: .mock)
        .padding()
}

#Preview("Searching") {
    TaskRowView(task: .mockSearching)
        .padding()
}

#Preview("Awaiting Approval") {
    TaskRowView(task: .mockAwaitingApproval)
        .padding()
}

#Preview("Stopped") {
    TaskRowView(task: .mockStopped)
        .padding()
}
