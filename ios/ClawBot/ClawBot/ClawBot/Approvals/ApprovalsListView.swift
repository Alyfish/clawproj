import SwiftUI

// MARK: - ApprovalsListView

struct ApprovalsListView: View {
    let pending: [ApprovalRequest]
    let history: [ResolvedApproval]
    var onSelectPending: ((ApprovalRequest) -> Void)?

    var body: some View {
        Group {
            if pending.isEmpty && history.isEmpty {
                emptyState
            } else {
                approvalsList
            }
        }
        .navigationTitle("Approvals")
        .navigationBarTitleDisplayMode(.inline)
    }

    // MARK: - List

    private var approvalsList: some View {
        List {
            if !pending.isEmpty {
                Section {
                    ForEach(pending) { request in
                        Button {
                            onSelectPending?(request)
                        } label: {
                            PendingApprovalRow(request: request)
                        }
                        .buttonStyle(.plain)
                    }
                } header: {
                    HStack(spacing: 6) {
                        Text("Pending")
                        Text("\(pending.count)")
                            .font(.caption2)
                            .fontWeight(.bold)
                            .foregroundStyle(.white)
                            .padding(.horizontal, 7)
                            .padding(.vertical, 2)
                            .background(.orange, in: Capsule())
                    }
                }
            }

            if !history.isEmpty {
                Section("History") {
                    ForEach(sortedHistory) { resolved in
                        ResolvedApprovalRow(resolved: resolved)
                    }
                }
            }
        }
        .listStyle(.insetGrouped)
    }

    // MARK: - Empty State

    private var emptyState: some View {
        VStack(spacing: 12) {
            Image(systemName: "checkmark.shield")
                .font(.system(size: 48))
                .foregroundStyle(.green)
            Text("No pending approvals")
                .font(.headline)
                .foregroundStyle(.secondary)
            Text("When ClawBot wants to book, pay, send, or take other actions on your behalf, it will ask for your approval here first.")
                .font(.subheadline)
                .foregroundStyle(.tertiary)
                .multilineTextAlignment(.center)
                .padding(.horizontal, 32)
        }
    }

    // MARK: - Sorting

    private var sortedHistory: [ResolvedApproval] {
        history.sorted { a, b in
            a.response.decidedAt > b.response.decidedAt
        }
    }
}

// MARK: - Previews

#Preview("With Pending & History") {
    NavigationStack {
        ApprovalsListView(
            pending: [.mockSubmit, .mockPay, .mockDelete],
            history: [.mockApproved, .mockDenied],
            onSelectPending: { _ in }
        )
    }
}

#Preview("Pending Only") {
    NavigationStack {
        ApprovalsListView(
            pending: ApprovalRequest.allMocks,
            history: []
        )
    }
}

#Preview("History Only") {
    NavigationStack {
        ApprovalsListView(
            pending: [],
            history: [.mockApproved, .mockDenied]
        )
    }
}

#Preview("Empty") {
    NavigationStack {
        ApprovalsListView(pending: [], history: [])
    }
}
