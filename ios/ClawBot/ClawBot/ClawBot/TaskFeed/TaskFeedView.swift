import SwiftUI

// MARK: - TaskFeedView

struct TaskFeedView: View {
    let tasks: [AgentTask]
    var onRefresh: (() async -> Void)?
    var onSelectTask: ((AgentTask) -> Void)?

    var body: some View {
        Group {
            if tasks.isEmpty {
                emptyState
            } else {
                taskList
            }
        }
        .navigationTitle("Tasks")
        .navigationBarTitleDisplayMode(.inline)
    }

    // MARK: - Task List

    private var taskList: some View {
        List(sortedTasks) { task in
            TaskRowView(task: task)
                .contentShape(Rectangle())
                .onTapGesture {
                    onSelectTask?(task)
                }
                .listRowInsets(EdgeInsets(top: 8, leading: 16, bottom: 8, trailing: 16))
        }
        .listStyle(.plain)
        .refreshable {
            await onRefresh?()
        }
    }

    // MARK: - Empty State

    private var emptyState: some View {
        VStack(spacing: 12) {
            Image(systemName: "clipboard")
                .font(.system(size: 48))
                .foregroundStyle(.tertiary)
            Text("No tasks yet")
                .font(.headline)
                .foregroundStyle(.secondary)
            Text("Start a conversation to create one.")
                .font(.subheadline)
                .foregroundStyle(.tertiary)
        }
    }

    // MARK: - Sorting

    private var sortedTasks: [AgentTask] {
        tasks.sorted { a, b in
            // Active tasks first
            if a.status.isActive != b.status.isActive {
                return a.status.isActive
            }
            // Then reverse chronological by updatedAt
            return a.updatedAt > b.updatedAt
        }
    }
}

// MARK: - Previews

#Preview("With items") {
    NavigationStack {
        TaskFeedView(
            tasks: [.mock, .mockSearching, .mockAwaitingApproval, .mockStopped],
            onRefresh: { try? await Task.sleep(for: .seconds(1)) },
            onSelectTask: { _ in }
        )
    }
}

#Preview("Empty") {
    NavigationStack {
        TaskFeedView(tasks: [])
    }
}
