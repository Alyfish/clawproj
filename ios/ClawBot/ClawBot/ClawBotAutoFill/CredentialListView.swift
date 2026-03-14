import SwiftUI

struct CredentialListItem: Identifiable {
    let id = UUID()
    let domain: String
    let username: String
}

struct CredentialListView: View {
    let credentials: [CredentialListItem]
    let onSelect: (CredentialListItem) -> Void
    let onCancel: () -> Void

    @State private var searchText = ""

    private var filtered: [CredentialListItem] {
        guard !searchText.isEmpty else { return credentials }
        let query = searchText.lowercased()
        return credentials.filter {
            $0.domain.lowercased().contains(query) ||
            $0.username.lowercased().contains(query)
        }
    }

    var body: some View {
        NavigationStack {
            Group {
                if credentials.isEmpty {
                    ContentUnavailableView(
                        "No Saved Passwords",
                        systemImage: "key.slash",
                        description: Text("ClawBot will save passwords as it logs into sites for you.")
                    )
                } else {
                    List(filtered) { item in
                        Button {
                            onSelect(item)
                        } label: {
                            VStack(alignment: .leading, spacing: 4) {
                                Text(item.domain)
                                    .font(.body)
                                Text(item.username)
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                            .padding(.vertical, 2)
                        }
                    }
                    .searchable(text: $searchText, prompt: "Search passwords")
                }
            }
            .navigationTitle("ClawBot Passwords")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel", action: onCancel)
                }
            }
        }
    }
}
