# Ownership & Borrowing — Deep Reference

## The Borrow Checker Mental Model

Three rules, always:
1. Each value has exactly one owner
2. You can have any number of shared references (`&T`) OR exactly one mutable reference (`&mut T`) — not both
3. References must not outlive the value they point to (enforced by lifetimes)

NLL (Non-Lexical Lifetimes): since Rust 2018, borrows end at their **last use**, not at the
closing `}`. This eliminates many false positives from earlier Rust.

## Lifetime Annotations

Only needed when the compiler can't infer the relationship between input and output lifetimes.

```rust
// Explicit: output lifetime tied to input
fn longest<'a>(a: &'a str, b: &'a str) -> &'a str {
    if a.len() > b.len() { a } else { b }
}

// Struct holding a reference must declare lifetime
struct Parser<'a> {
    input: &'a str,
    pos: usize,
}

impl<'a> Parser<'a> {
    fn remaining(&self) -> &'a str {
        &self.input[self.pos..]
    }
}
```

## Elision Rules (when you DON'T need annotations)

1. Each reference parameter gets its own lifetime
2. If exactly one input lifetime, it's assigned to all outputs
3. If `&self` or `&mut self` is one of the inputs, its lifetime is assigned to all outputs

```rust
// All of these work without annotations:
fn first_word(s: &str) -> &str { .. }         // rule 2
fn push(&mut self, item: T) { .. }             // rule 3
fn longest_prefix(&self, s: &str) -> &str { .. } // rule 3 — output tied to self
```

## `'static` Lifetime

Means the value lives for the entire program duration. Common cases:
- String literals: `"hello"` is `&'static str`
- Data stored in a `static` or `const`
- Types with no borrows: any `T: 'static` means T owns all its data

```rust
// Spawning tasks requires 'static (task may outlive the spawner)
tokio::spawn(async move { .. }); // captured values must be 'static + Send
```

## `Pin<P>` and Self-Referential Types

Required for async machinery and types that must not move in memory.

```rust
use std::pin::Pin;

// Futures returned by async fn are self-referential; they must be pinned to poll
let mut fut = Box::pin(some_async_fn());
fut.as_mut().poll(&mut cx);

// Pin projection: access pinned fields safely
// Use the `pin-project` crate rather than rolling your own
use pin_project::pin_project;

#[pin_project]
struct MyFuture {
    #[pin]
    inner: SomeOtherFuture,
    state: u32, // not pinned, can be accessed normally
}
```

## `Cow<'_, T>` — Clone on Write

Use when a function sometimes returns borrowed data, sometimes owned:

```rust
use std::borrow::Cow;

fn normalize(input: &str) -> Cow<'_, str> {
    if input.chars().all(|c| c.is_lowercase()) {
        Cow::Borrowed(input)   // no allocation
    } else {
        Cow::Owned(input.to_lowercase())  // allocates only when needed
    }
}
```

## Common Borrow Checker Workarounds

### Entry API instead of double lookup
```rust
// Instead of: check + insert
let val = map.entry(key).or_insert_with(|| expensive());
```

### Splitting borrows
```rust
struct State { a: Vec<u8>, b: Vec<u8> }

// Can't borrow a and b mutably through self at the same time
// Split via methods or destructure:
let State { a, b } = &mut state;
a.push(1);
b.push(2);
```

### `split_at_mut` for disjoint slices
```rust
let (left, right) = slice.split_at_mut(mid);
// left and right are non-overlapping — both mutably borrowable
```

### Index workaround with clone when necessary
```rust
// Sometimes unavoidable; document why
let key = map.keys().next().cloned(); // clone the key to release the borrow
if let Some(k) = key {
    map.remove(&k);
}
```
