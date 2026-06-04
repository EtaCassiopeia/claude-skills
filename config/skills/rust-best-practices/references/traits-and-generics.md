# Traits & Generics — Deep Reference

## When to Use Generics vs `dyn Trait`

| | Generics `<T: Trait>` | `dyn Trait` |
|--|--|--|
| Performance | Zero-cost (monomorphized) | Vtable dispatch overhead |
| Binary size | Can bloat (one copy per T) | Single implementation |
| Heterogeneous collections | No (all items must be same T) | Yes |
| Object safety required | No | Yes |
| Best for | Hot paths, small T sets | Plugin systems, event handlers |

## Object Safety Rules

A trait is object-safe if:
- No methods return `Self`
- No methods have generic type parameters
- No `where Self: Sized` bounds (on non-dispatchable methods, `where Self: Sized` is OK)

```rust
// NOT object-safe: returns Self
trait Clone { fn clone(&self) -> Self; }

// Object-safe: take &self, return concrete type
trait Serialize {
    fn serialize(&self) -> Vec<u8>;
}
let s: Box<dyn Serialize> = ...; // works
```

## Higher-Ranked Trait Bounds (HRTBs)

Use `for<'a>` when a trait must hold for all lifetimes:

```rust
// F must work for any lifetime 'a
fn apply<F>(f: F, s: &str) -> &str
where
    F: for<'a> Fn(&'a str) -> &'a str,
{
    f(s)
}
```

## Blanket Implementations

```rust
// Implement Display for all types that implement Debug (example, don't actually do this)
impl<T: std::fmt::Debug> std::fmt::Display for Wrapper<T> {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{:?}", self.0)
    }
}
```

Blanket impls can cause coherence (orphan rule) conflicts. Rules:
- Either the trait OR the type must be defined in your crate
- Can't implement foreign traits on foreign types

## The Newtype Pattern

Workaround for orphan rule, also adds type safety:

```rust
struct Meters(f64);
struct Seconds(f64);

// Now Meters and Seconds are distinct types — can't accidentally mix them
impl std::ops::Add for Meters {
    type Output = Meters;
    fn add(self, rhs: Meters) -> Meters { Meters(self.0 + rhs.0) }
}
```

## Associated Types vs Generic Parameters

```rust
// Associated type: one natural output per implementing type
trait Iterator {
    type Item;  // each impl picks exactly one Item type
    fn next(&mut self) -> Option<Self::Item>;
}

// Generic parameter: multiple impls per type (e.g., From<i32>, From<String>)
trait From<T> {
    fn from(value: T) -> Self;
}
```

Use associated types when there's a canonical single answer.
Use generic parameters when a type may implement the trait for multiple input types.

## Useful Standard Traits Checklist

| Trait | Implement when |
|-------|----------------|
| `Debug` | Always |
| `Display` | Type has a human-readable form |
| `Clone` | Duplication is meaningful |
| `Copy` | Type is small, stack-only, cheap to copy |
| `PartialEq` / `Eq` | Equality comparison makes sense |
| `Hash` | Used as HashMap key (requires `Eq`) |
| `PartialOrd` / `Ord` | Ordering makes sense |
| `Default` | Sensible zero value exists |
| `From<T>` / `Into<T>` | Lossless conversion from/to T |
| `FromStr` | Can be parsed from a string |
| `Deref` / `DerefMut` | Smart pointer or wrapper type |

## Impl Trait in Return Position (RPIT)

```rust
// Returns some iterator — caller doesn't know the concrete type
fn evens(v: &[i32]) -> impl Iterator<Item = &i32> {
    v.iter().filter(|&&x| x % 2 == 0)
}

// NOT usable in traits until async fn in traits stabilizes fully
// Use #[async_trait] or box the return: Box<dyn Iterator<...>>
```
