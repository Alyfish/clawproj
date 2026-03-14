import Testing
import Foundation
@testable import ClawBot

// MARK: - TaskStore Tests

struct TaskStoreTests {

    private func makeTempDir() -> URL {
        FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
    }

    @Test func saveAndLoadRoundTrips() async throws {
        let dir = makeTempDir()
        let store = TaskStore(directory: dir)

        try await store.save(tasks: [.mock], pendingApprovals: [.mock])
        let loaded = try await store.load()

        #expect(loaded.tasks.count == 1)
        #expect(loaded.tasks[0].id == "task-001")
        #expect(loaded.tasks[0].goal == "Find the cheapest round-trip flight from SFO to JFK next weekend")
        #expect(loaded.pendingApprovals.count == 1)
        #expect(loaded.pendingApprovals[0].id == "approval-001")

        try await store.clearAll()
    }

    @Test func loadReturnsEmptyWhenNoFile() async throws {
        let dir = makeTempDir()
        let store = TaskStore(directory: dir)

        let loaded = try await store.load()

        #expect(loaded.tasks.isEmpty)
        #expect(loaded.pendingApprovals.isEmpty)
    }

    @Test func corruptFileThrowsDecodingError() async throws {
        let dir = makeTempDir()
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let file = dir.appendingPathComponent("tasks.json")
        try "not valid json at all".data(using: .utf8)!.write(to: file)

        let store = TaskStore(directory: dir)

        do {
            _ = try await store.load()
            Issue.record("Expected load to throw on corrupt file")
        } catch {
            #expect(error is DecodingError)
        }

        try FileManager.default.removeItem(at: dir)
    }

    @Test func clearAllRemovesDirectory() async throws {
        let dir = makeTempDir()
        let store = TaskStore(directory: dir)

        try await store.save(tasks: [.mock], pendingApprovals: [])
        #expect(FileManager.default.fileExists(atPath: dir.path))

        try await store.clearAll()
        #expect(!FileManager.default.fileExists(atPath: dir.path))
    }

    @Test func multipleTasksPreserveOrder() async throws {
        let dir = makeTempDir()
        let store = TaskStore(directory: dir)

        let tasks: [AgentTask] = [.mock, .mockSearching, .mockAwaitingApproval, .mockStopped]
        try await store.save(tasks: tasks, pendingApprovals: [])
        let loaded = try await store.load()

        #expect(loaded.tasks.count == 4)
        #expect(loaded.tasks[0].id == "task-001")
        #expect(loaded.tasks[1].id == "task-002")
        #expect(loaded.tasks[2].id == "task-003")
        #expect(loaded.tasks[3].id == "task-004")
        #expect(loaded.tasks[0].status == .completed)
        #expect(loaded.tasks[1].status == .searching)

        try await store.clearAll()
    }
}

// MARK: - ApprovalStore Tests

struct ApprovalStoreTests {

    private func makeTempDir() -> URL {
        FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
    }

    @Test func saveAndLoadRoundTrips() async throws {
        let dir = makeTempDir()
        let store = ApprovalStore(directory: dir)

        // Use a fresh date so the pending request isn't expired by the 24h stale filter
        let freshRequest = ApprovalRequest(
            id: "approval-101",
            taskId: "task-003",
            action: .submit,
            description: "Submit rental application",
            details: ["property": "245 Bedford Ave"],
            createdAt: ISO8601DateFormatter().string(from: Date())
        )
        try await store.save(pending: [freshRequest], history: [.mockApproved])
        let loaded = try await store.load()

        #expect(loaded.pending.count == 1)
        #expect(loaded.pending[0].id == "approval-101")
        #expect(loaded.history.count == 1)
        #expect(loaded.history[0].request.id == "approval-102")

        try await store.clearAll()
    }

    @Test func staleApprovalsExpiredOnLoad() async throws {
        let dir = makeTempDir()
        // Use 0-second threshold so everything is stale
        let store = ApprovalStore(directory: dir, staleThreshold: 0)

        let staleRequest = ApprovalRequest(
            id: "stale-1",
            taskId: "task-1",
            action: .pay,
            description: "Old approval",
            details: [:],
            createdAt: "2020-01-01T00:00:00Z"
        )
        try await store.save(pending: [staleRequest], history: [])

        // Brief pause so threshold of 0 triggers
        try await Task.sleep(nanoseconds: 10_000_000) // 10ms

        let loaded = try await store.load()
        #expect(loaded.pending.isEmpty)

        try await store.clearAll()
    }

    @Test func freshApprovalsKeptOnLoad() async throws {
        let dir = makeTempDir()
        let store = ApprovalStore(directory: dir)

        let freshRequest = ApprovalRequest(
            id: "fresh-1",
            taskId: "task-1",
            action: .submit,
            description: "Recent approval",
            details: [:],
            createdAt: ISO8601DateFormatter().string(from: Date())
        )
        try await store.save(pending: [freshRequest], history: [])
        let loaded = try await store.load()

        #expect(loaded.pending.count == 1)
        #expect(loaded.pending[0].id == "fresh-1")

        try await store.clearAll()
    }

    @Test func historyNotAffectedByExpiry() async throws {
        let dir = makeTempDir()
        // Use 0-second threshold
        let store = ApprovalStore(directory: dir, staleThreshold: 0)

        try await store.save(pending: [], history: [.mockApproved, .mockDenied])

        try await Task.sleep(nanoseconds: 10_000_000) // 10ms

        let loaded = try await store.load()
        #expect(loaded.history.count == 2)

        try await store.clearAll()
    }

    @Test func unparsableDateTreatedAsStale() async throws {
        let dir = makeTempDir()
        let store = ApprovalStore(directory: dir)

        let badDateRequest = ApprovalRequest(
            id: "bad-date",
            taskId: "task-1",
            action: .send,
            description: "Bad date",
            details: [:],
            createdAt: "not-a-date"
        )
        try await store.save(pending: [badDateRequest], history: [])
        let loaded = try await store.load()

        #expect(loaded.pending.isEmpty)

        try await store.clearAll()
    }
}

// MARK: - WatchlistStore Tests

struct WatchlistStoreTests {

    private func makeTempDir() -> URL {
        FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
    }

    @Test func saveAndLoadRoundTrips() async throws {
        let dir = makeTempDir()
        let store = WatchlistStore(directory: dir)

        try await store.save(items: [.mockPriceWatch], alerts: [.mockPriceDrop])
        let loaded = try await store.load()

        #expect(loaded.items.count == 1)
        #expect(loaded.items[0].id == "watch-001")
        #expect(loaded.items[0].type == .priceWatch)
        #expect(loaded.alerts.count == 1)
        #expect(loaded.alerts[0].id == "alert-001")

        try await store.clearAll()
    }

    @Test func isReadStatePreserved() async throws {
        let dir = makeTempDir()
        let store = WatchlistStore(directory: dir)

        // Save an alert with isRead = false (default)
        try await store.save(items: [], alerts: [.mockPriceDrop])
        let loaded1 = try await store.load()
        #expect(loaded1.alerts[0].isRead == false)

        // Now save with isRead = true
        var readAlert = WatchlistAlert(
            id: "alert-read",
            watchId: "watch-001",
            alertType: "price_drop",
            title: "Test",
            message: "Test message",
            source: "test",
            previousValue: nil,
            currentValue: nil,
            url: nil,
            cardType: nil,
            timestamp: "2026-02-28T11:00:00Z",
            isRead: true
        )
        _ = readAlert // suppress warning
        try await store.save(items: [], alerts: [readAlert])
        let loaded2 = try await store.load()

        #expect(loaded2.alerts[0].isRead == true)
        #expect(loaded2.alerts[0].id == "alert-read")

        try await store.clearAll()
    }

    @Test func alertsCappedAt100OnSave() async throws {
        let dir = makeTempDir()
        let store = WatchlistStore(directory: dir)

        let manyAlerts = (0..<150).map { i in
            WatchlistAlert(
                id: "alert-\(i)",
                watchId: "watch-001",
                alertType: "price_drop",
                title: "Alert \(i)",
                message: "Message \(i)",
                source: "test",
                previousValue: nil,
                currentValue: nil,
                url: nil,
                cardType: nil,
                timestamp: ISO8601DateFormatter().string(from: Date())
            )
        }

        try await store.save(items: [], alerts: manyAlerts)
        let loaded = try await store.load()

        #expect(loaded.alerts.count == 100)
        #expect(loaded.alerts[0].id == "alert-0")
        #expect(loaded.alerts[99].id == "alert-99")

        try await store.clearAll()
    }

    @Test func loadReturnsEmptyWhenNoFile() async throws {
        let dir = makeTempDir()
        let store = WatchlistStore(directory: dir)

        let loaded = try await store.load()

        #expect(loaded.items.isEmpty)
        #expect(loaded.alerts.isEmpty)
    }

    @Test func multipleItemsPreserveAllFields() async throws {
        let dir = makeTempDir()
        let store = WatchlistStore(directory: dir)

        let items: [WatchlistItem] = [.mockPriceWatch, .mockNewListing, .mockLineMovement]
        try await store.save(items: items, alerts: [])
        let loaded = try await store.load()

        #expect(loaded.items.count == 3)
        #expect(loaded.items[0].active == true)
        #expect(loaded.items[2].active == false)
        #expect(loaded.items[1].type == .newListing)
        #expect(loaded.items[0].filters["origin"] == "SFO")

        try await store.clearAll()
    }
}
