---
path_scope:
  - "**/*.scala"
  - "**/*.sc"
  - "**/build.sbt"
---

# Scala 3 Type-Level Rules — Library Authors

## Variance

- Covariant (`+A`): `A` appears only in output / return positions — producers, read-only containers
- Contravariant (`-A`): `A` appears only in input / parameter positions — consumers, encoders, comparators
- Invariant (no annotation): `A` appears in both positions (codecs), or the type is mutable
- Trust the compiler's variance error — if it rejects `+A`, there is an input position; fix the design
- Never use `asInstanceOf` to work around variance — it produces unsound code

## GADTs

- Use `enum Expr[A]` with `extends Expr[ConcreteType]` per case for typed expression trees
- Let the GADT refine types in pattern match branches — no `asInstanceOf` needed
- Use type witness `case class Refl[A]() extends ===[A, A]` to prove type equality at runtime

## Type Lambdas and HKTs

- Use native Scala 3 type lambdas `[X] =>> F[X, E]` — never add kind-projector plugin
- Constrain `F[_]` to the least powerful typeclass: `Functor` < `Applicative` < `Monad`
- Use `Bifunctor[F[_, _]]`, `Contravariant[F[-_]]` when the extra variance carries meaning

## Match Types

- Keep match types shallow — deep recursion produces unreadable error messages
- Break long match type chains into named intermediate type aliases
- Use `Elem[X]` pattern (match type alias) for dependent return types in generic APIs

## Generic Derivation

- Prefer **Magnolia** for typeclass derivation — `join`/`split` API with labels and annotations
- Use Scala 3 **`Mirror`** directly only for simple cases or when you want zero dependencies
- Use **Shapeless 3** only for HList-style generic traversal or poly functions, not for typeclasses
- Always expose derivation as a `derives` clause, never require users to summon internals

## `compiletime` and `inline`

- Reserve `compiletime.ops` for genuine type-level proofs in library APIs, not business logic
- Prefer `error("msg")` over letting the compiler emit generic "type mismatch" for bad inputs
- Use `inline if` + `error` to reject invalid literal type arguments at compile time
- `summonAll` / `summonInline` over `implicitly` — never use `implicitly` in Scala 3

## General Library Design

- Use `opaque type` for zero-cost newtypes — never `AnyVal` extends
- Use phantom types (`sealed trait Unvalidated; class Form[S]`) for compile-time state machines
- Keep `given` instances in companion objects for automatic discovery — not in package objects
- `-Xfatal-warnings` in CI — no warnings in library code
