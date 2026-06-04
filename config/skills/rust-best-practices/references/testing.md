# Testing — Deep Reference

## Test Organization

```
src/
  lib.rs
  storage.rs       ← unit tests at bottom in #[cfg(test)] mod
tests/
  integration.rs   ← tests public API as external crate
  fixtures/        ← shared test data
benches/
  throughput.rs    ← criterion benchmarks
```

## Unit Tests

```rust
// At the bottom of each source file
#[cfg(test)]
mod tests {
    use super::*;  // access private items

    #[test]
    fn parses_valid_input() {
        let result = parse("valid").expect("should parse");
        assert_eq!(result.value, 42);
    }

    #[test]
    #[should_panic(expected = "overflow")]
    fn panics_on_overflow() {
        parse("999999999999");
    }
}
```

## Integration Tests

```rust
// tests/storage_test.rs — only public API
use mylib::Storage;

#[test]
fn roundtrip_put_get() {
    let store = Storage::in_memory();
    store.put("k", b"v").unwrap();
    assert_eq!(store.get("k").unwrap(), Some(b"v".to_vec()));
}
```

## Async Tests

```rust
#[tokio::test]
async fn fetches_data() {
    let client = HttpClient::new();
    let data = client.get("https://example.com").await.unwrap();
    assert!(!data.is_empty());
}

// With timeout
#[tokio::test(flavor = "multi_thread")]
async fn concurrent_requests() { .. }
```

## Property-Based Testing (proptest)

```rust
use proptest::prelude::*;

proptest! {
    #[test]
    fn encode_decode_roundtrip(data: Vec<u8>) {
        let encoded = encode(&data);
        let decoded = decode(&encoded).unwrap();
        prop_assert_eq!(data, decoded);
    }

    #[test]
    fn sort_is_idempotent(mut v: Vec<i32>) {
        v.sort();
        let sorted_once = v.clone();
        v.sort();
        prop_assert_eq!(sorted_once, v);
    }
}
```

## Snapshot Testing (insta)

```rust
use insta::assert_snapshot;

#[test]
fn renders_config() {
    let cfg = Config::default();
    assert_snapshot!(cfg.to_toml_string());
    // First run: creates snapshot file; subsequent runs: compare
}

// Update snapshots: cargo insta review
```

## Mocking

Prefer dependency injection with trait objects over mock frameworks:

```rust
pub trait HttpClient: Send + Sync {
    async fn get(&self, url: &str) -> Result<Bytes>;
}

// Test double
struct FakeClient { response: Bytes }

#[async_trait]
impl HttpClient for FakeClient {
    async fn get(&self, _url: &str) -> Result<Bytes> {
        Ok(self.response.clone())
    }
}

#[tokio::test]
async fn uses_fake_client() {
    let client = FakeClient { response: b"hello".into() };
    let svc = MyService::new(client);
    assert_eq!(svc.fetch_data().await.unwrap(), b"hello");
}
```

If you need a mock framework: `mockall` is the standard choice.

## Benchmarks (Criterion)

```rust
use criterion::{black_box, criterion_group, criterion_main, Criterion};

fn bench_parse(c: &mut Criterion) {
    c.bench_function("parse 1kb", |b| {
        b.iter(|| parse(black_box("input data...")))
    });
}

criterion_group!(benches, bench_parse);
criterion_main!(benches);
```

Run: `cargo bench`

## Test Helpers & Fixtures

```rust
// Use builder pattern for test fixtures
fn make_user() -> User {
    User::builder()
        .name("test")
        .email("test@example.com")
        .build()
}

// tempfile crate for temporary directories
use tempfile::tempdir;
let dir = tempdir().unwrap();
let path = dir.path().join("test.db");
// dir cleaned up on drop
```
