import Testing
import Foundation
@testable import ClawBot

// MARK: - CredentialStore Tests

struct CredentialStoreTests {

    // On simulator, kSecAttrAccessGroup is ignored — tests work without provisioning.
    // Each test calls deleteAll() to ensure clean state.

    @Test func saveAndRetrieveCredential() {
        let store = CredentialStore()
        store.deleteAll()

        let saved = store.save(domain: "example.com", username: "user@test.com", password: "pass123")
        #expect(saved == true)

        let creds = store.getCredentials(for: "example.com")
        #expect(creds.count == 1)
        #expect(creds[0].username == "user@test.com")
        #expect(creds[0].password == "pass123")

        store.deleteAll()
    }

    @Test func updateExistingCredential() {
        let store = CredentialStore()
        store.deleteAll()

        store.save(domain: "example.com", username: "user@test.com", password: "oldpass")
        store.save(domain: "example.com", username: "user@test.com", password: "newpass")

        let creds = store.getCredentials(for: "example.com")
        #expect(creds.count == 1)
        #expect(creds[0].password == "newpass")

        store.deleteAll()
    }

    @Test func getAllDomainsReturnsSortedUnique() {
        let store = CredentialStore()
        store.deleteAll()

        store.save(domain: "b.com", username: "user1", password: "p1")
        store.save(domain: "a.com", username: "user2", password: "p2")
        store.save(domain: "b.com", username: "user3", password: "p3")

        let domains = store.getAllDomains()
        #expect(domains == ["a.com", "b.com"])

        store.deleteAll()
    }

    @Test func credentialCountReflectsStoredItems() {
        let store = CredentialStore()
        store.deleteAll()

        #expect(store.credentialCount() == 0)

        store.save(domain: "a.com", username: "u1", password: "p1")
        store.save(domain: "b.com", username: "u2", password: "p2")

        #expect(store.credentialCount() == 2)

        store.deleteAll()
    }

    @Test func deleteAllClearsEverything() {
        let store = CredentialStore()

        store.save(domain: "example.com", username: "user", password: "pass")
        #expect(store.credentialCount() > 0)

        let deleted = store.deleteAll()
        #expect(deleted == true)
        #expect(store.credentialCount() == 0)
    }

    @Test func getCredentialsForNonexistentDomainReturnsEmpty() {
        let store = CredentialStore()
        store.deleteAll()

        let creds = store.getCredentials(for: "nonexistent.example.com")
        #expect(creds.isEmpty)

        store.deleteAll()
    }
}
