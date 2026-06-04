# Async & Tokio — Deep Reference

## Runtime Setup

```rust
// Binary: full multi-thread runtime
#[tokio::main]
async fn main() -> anyhow::Result<()> { .. }

// Library tests: use tokio::test
#[tokio::test]
async fn test_fetch() { .. }

// Fine-grained control
let rt = tokio::runtime::Builder::new_multi_thread()
    .worker_threads(4)
    .enable_all()
    .build()?;
rt.block_on(async { .. });
```

## Task Spawning

```rust
// Concurrent, independent tasks
let handle = tokio::spawn(async move { fetch(url).await });
let result = handle.await??; // outer ? = JoinError, inner ? = task error

// Wait for multiple tasks
let (a, b) = tokio::join!(task_a(), task_b()); // waits for both
let first = tokio::select! {  // takes whichever finishes first
    a = task_a() => a,
    b = task_b() => b,
};

// CPU-bound / blocking work — NEVER block executor threads
let result = tokio::task::spawn_blocking(|| heavy_computation()).await?;
```

## Cancellation (tokio_util)

```rust
use tokio_util::sync::CancellationToken;

let token = CancellationToken::new();
let child = token.child_token();

tokio::spawn(async move {
    tokio::select! {
        _ = child.cancelled() => println!("cancelled"),
        result = do_work() => println!("done: {result:?}"),
    }
});

token.cancel(); // signals all child tokens
```

## Channels

| Channel | Use Case |
|---------|----------|
| `mpsc` | Many producers, one consumer (work queues) |
| `oneshot` | Single response (request/reply) |
| `broadcast` | Fan-out to multiple consumers |
| `watch` | Latest-value subscription (config updates) |

```rust
// mpsc: worker pool pattern
let (tx, mut rx) = tokio::sync::mpsc::channel::<Work>(32);

tokio::spawn(async move {
    while let Some(work) = rx.recv().await {
        process(work).await;
    }
});

tx.send(Work::new()).await?;
```

## Async Traits

```rust
// Stable Rust: use async-trait crate
use async_trait::async_trait;

#[async_trait]
pub trait Fetcher: Send + Sync {
    async fn fetch(&self, url: &str) -> Result<Bytes>;
}

#[async_trait]
impl Fetcher for HttpFetcher {
    async fn fetch(&self, url: &str) -> Result<Bytes> { .. }
}
```

## Common Pitfalls

### Mutex across await
```rust
// BAD: std::sync::Mutex held across await
async fn bad(state: Arc<std::sync::Mutex<i32>>) {
    let mut g = state.lock().unwrap();
    tokio::time::sleep(Duration::from_secs(1)).await; // holds lock!
    *g += 1;
}

// GOOD option 1: tokio::sync::Mutex
async fn good(state: Arc<tokio::sync::Mutex<i32>>) {
    let mut g = state.lock().await;
    *g += 1;
    // drop before any await
}

// GOOD option 2: scope the lock, drop before await
async fn good2(state: Arc<std::sync::Mutex<i32>>) {
    {
        let mut g = state.lock().unwrap();
        *g += 1;
    } // dropped here
    tokio::time::sleep(Duration::from_secs(1)).await;
}
```

### Timeout pattern
```rust
use tokio::time::{timeout, Duration};

match timeout(Duration::from_secs(5), fetch(url)).await {
    Ok(Ok(data)) => handle(data),
    Ok(Err(e)) => eprintln!("fetch error: {e}"),
    Err(_elapsed) => eprintln!("timed out"),
}
```

## Stream Processing

```rust
use tokio_stream::{StreamExt, wrappers::ReceiverStream};

let stream = ReceiverStream::new(rx);
tokio::pin!(stream);

while let Some(item) = stream.next().await {
    process(item).await;
}
```
