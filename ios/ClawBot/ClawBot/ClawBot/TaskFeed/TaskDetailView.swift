import SwiftUI

struct TaskDetailView: View {
    let task: AgentTask
    let pendingApprovals: [PendingApproval]
    var onStopTask: ((String) -> Void)?
    var onApprove: ((String) -> Void)?
    var onDeny: ((String) -> Void)?

    @State private var showStopConfirmation = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                headerSection
                stepsSection
                if !taskApprovals.isEmpty { approvalsSection }
                if !task.cardIds.isEmpty { cardsStubSection }
                timestampsSection
                if task.status.isActive { stopSection }
            }
            .padding()
        }
        .navigationTitle("Task Details")
        .navigationBarTitleDisplayMode(.inline)
    }

    // MARK: - Header

    private var headerSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                StatusBadge(status: task.status)
                Spacer()
                if task.status.isActive {
                    ProgressView()
                        .controlSize(.small)
                }
            }

            Text(task.goal)
                .font(.title3)
                .fontWeight(.semibold)
        }
    }

    // MARK: - Steps

    private var stepsSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Steps")
                .font(.headline)

            ForEach(task.steps) { step in
                HStack(alignment: .top, spacing: 10) {
                    stepIcon(for: step.status)
                        .frame(width: 20)

                    VStack(alignment: .leading, spacing: 2) {
                        Text(step.description)
                            .font(.subheadline)

                        if let tool = step.toolName {
                            Text(tool)
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                                .padding(.horizontal, 6)
                                .padding(.vertical, 2)
                                .background(Color(.systemGray6))
                                .clipShape(Capsule())
                        }

                        if let result = step.result {
                            Text(result)
                                .font(.caption)
                                .foregroundStyle(.tertiary)
                                .lineLimit(2)
                        }
                    }

                    Spacer()
                }
                .padding(.vertical, 4)

                if step.id != task.steps.last?.id {
                    // Connector line
                    Rectangle()
                        .fill(Color(.systemGray5))
                        .frame(width: 2, height: 8)
                        .padding(.leading, 9)  // center under icon
                }
            }
        }
        .padding()
        .background(Color(.systemGray6).opacity(0.5))
        .clipShape(RoundedRectangle(cornerRadius: 12))
    }

    @ViewBuilder
    private func stepIcon(for status: ThinkingStepStatus) -> some View {
        switch status {
        case .pending:
            Image(systemName: "circle.dotted")
                .foregroundStyle(.tertiary)
        case .running:
            ProgressView()
                .controlSize(.mini)
        case .done:
            Image(systemName: "checkmark.circle.fill")
                .foregroundStyle(.green)
        case .error:
            Image(systemName: "xmark.circle.fill")
                .foregroundStyle(.red)
        }
    }

    // MARK: - Approvals

    private var approvalsSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Pending Approvals")
                .font(.headline)

            ForEach(taskApprovals) { approval in
                VStack(alignment: .leading, spacing: 8) {
                    HStack(spacing: 6) {
                        Image(systemName: "exclamationmark.shield.fill")
                            .foregroundStyle(.orange)
                        Text(approval.action.uppercased())
                            .font(.caption)
                            .fontWeight(.bold)
                            .foregroundStyle(.orange)
                    }

                    Text(approval.description)
                        .font(.subheadline)

                    HStack(spacing: 12) {
                        Button(action: { onApprove?(approval.id) }) {
                            HStack {
                                Image(systemName: "checkmark")
                                Text("Approve")
                            }
                            .font(.subheadline)
                            .fontWeight(.medium)
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 10)
                            .background(.green)
                            .foregroundStyle(.white)
                            .clipShape(RoundedRectangle(cornerRadius: 10))
                        }

                        Button(action: { onDeny?(approval.id) }) {
                            HStack {
                                Image(systemName: "xmark")
                                Text("Deny")
                            }
                            .font(.subheadline)
                            .fontWeight(.medium)
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 10)
                            .background(.red.opacity(0.12))
                            .foregroundStyle(.red)
                            .clipShape(RoundedRectangle(cornerRadius: 10))
                        }
                    }
                }
                .padding()
                .background(Color.orange.opacity(0.06))
                .clipShape(RoundedRectangle(cornerRadius: 12))
            }
        }
    }

    private var taskApprovals: [PendingApproval] {
        pendingApprovals.filter { $0.taskId == task.id }
    }

    // MARK: - Cards Stub

    private var cardsStubSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Results")
                .font(.headline)

            // Stub — CardListView will replace this when integrated
            HStack(spacing: 8) {
                Image(systemName: "rectangle.stack")
                    .foregroundStyle(.blue)
                Text("\(task.cardIds.count) cards available")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
            .padding()
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Color(.systemGray6))
            .clipShape(RoundedRectangle(cornerRadius: 12))
        }
    }

    // MARK: - Timestamps

    private var timestampsSection: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text("Created:")
                    .font(.caption)
                    .foregroundStyle(.tertiary)
                Text(formatDate(task.createdAt))
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            HStack {
                Text("Updated:")
                    .font(.caption)
                    .foregroundStyle(.tertiary)
                Text(formatDate(task.updatedAt))
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
    }

    // MARK: - Stop

    private var stopSection: some View {
        Button(action: { showStopConfirmation = true }) {
            HStack {
                Image(systemName: "stop.circle.fill")
                Text("Stop Task")
            }
            .font(.subheadline)
            .fontWeight(.medium)
            .frame(maxWidth: .infinity)
            .padding(.vertical, 12)
            .background(.red.opacity(0.12))
            .foregroundStyle(.red)
            .clipShape(RoundedRectangle(cornerRadius: 12))
        }
        .confirmationDialog("Stop this task?", isPresented: $showStopConfirmation) {
            Button("Stop Task", role: .destructive) {
                onStopTask?(task.id)
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("This will cancel any pending actions and stop the agent.")
        }
    }

    // MARK: - Helpers

    private func formatDate(_ iso: String) -> String {
        guard let date = ISO8601DateFormatter().date(from: iso) else { return iso }
        let formatter = DateFormatter()
        formatter.dateStyle = .medium
        formatter.timeStyle = .short
        return formatter.string(from: date)
    }
}

// MARK: - Previews

#Preview("Completed task") {
    NavigationStack {
        TaskDetailView(task: .mock, pendingApprovals: [])
    }
}

#Preview("Searching — in progress") {
    NavigationStack {
        TaskDetailView(task: .mockSearching, pendingApprovals: [])
    }
}

#Preview("Awaiting approval") {
    NavigationStack {
        TaskDetailView(
            task: .mockAwaitingApproval,
            pendingApprovals: [.mock],
            onApprove: { id in print("Approved \(id)") },
            onDeny: { id in print("Denied \(id)") }
        )
    }
}

#Preview("Stopped") {
    NavigationStack {
        TaskDetailView(task: .mockStopped, pendingApprovals: [])
    }
}
