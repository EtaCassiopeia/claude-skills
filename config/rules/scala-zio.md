---
path_scope:
  - "**/*.scala"
  - "**/*.sc"
  - "**/build.sbt"
---

# Scala 3 + ZIO 2 Development Rules

## Scala 3 Syntax

- Use `enum` instead of `sealed trait` + `case object`/`case class` hierarchies
- Use `opaque type` instead of `AnyVal` wrappers for zero-cost newtypes
- Use `given`/`using` instead of `implicit` — never use `implicit` keyword
- Use `extension` methods instead of implicit classes
- Use `derives` clause for typeclass derivation
- Use significant indentation (braceless syntax) consistently OR braces consistently — don't mix
- Use union types (`A | B`) where appropriate instead of sealed hierarchies for simple cases

## ZIO 2 Service Pattern

Follow the Service Pattern 2.0 — no `Has[]`, no accessor methods:

```scala
// 1. Trait (service interface)
trait UserRepo:
  def find(id: UserId): IO[UserNotFound, User]
  def save(user: User): UIO[Unit]

// 2. Implementation
case class UserRepoLive(db: Database) extends UserRepo:
  def find(id: UserId): IO[UserNotFound, User] = ???
  def save(user: User): UIO[Unit] = ???

// 3. ZLayer constructor
object UserRepoLive:
  val layer: URLayer[Database, UserRepo] =
    ZLayer.derive[UserRepoLive]
```

## ZIO Effect Types

- Use the least powerful type alias that fits:
  - `UIO[A]` — no environment, no errors
  - `URIO[R, A]` — has environment, no errors
  - `Task[A]` — no environment, can fail with Throwable
  - `IO[E, A]` — no environment, typed error
  - `ZIO[R, E, A]` — only when you need all three
- Never use `ZIO[Any, Nothing, A]` when `UIO[A]` suffices
- Use `ZIO.serviceWithZIO` to access services

## Error Handling

- Define typed error ADTs per service boundary:
  ```scala
  enum AppError:
    case NotFound(entity: String, id: String)
    case ValidationFailed(errors: NonEmptyChunk[String])
    case Unauthorized(reason: String)
  ```
- Failures (typed errors) vs defects (unexpected): keep the distinction clear
- Use `refineOrDie` to narrow error channels when unexpected errors should be defects
- Don't log errors reflexively — let them propagate up the effect chain
- Handle errors at the outermost boundary (main, HTTP handler, etc.)

## ZLayer Composition

- Use `ZLayer.make` at the application entry point — it auto-wires the full dependency graph
- Keep layers flat: avoid long `>>>` chains; wire at the top
- Use `provide(layer1, layer2, ...)` in tests (not `ZLayer.make`) for clarity
- Use `.provideSomeShared` in test suites for expensive resources shared across tests
- `ZLayer.scoped` for layers that own resources; finalization order is reverse-acquisition

## Testing

- Use `zio-test` with `ZIOSpecDefault` as the base:
  ```scala
  object UserRepoSpec extends ZIOSpecDefault:
    def spec = suite("UserRepo")(
      test("finds existing user") {
        for
          repo <- ZIO.service[UserRepo]
          user <- repo.find(UserId("1"))
        yield assertTrue(user.name == "Alice")
      }
    ).provide(testLayer)
  ```
- Use `Gen` and `check` for property-based testing
- Provide test layers with in-memory implementations, not mocks
- Test error paths: verify correct error types propagate

## ZIO Prelude

Prefer ZIO Prelude over Cats for typeclass machinery in ZIO projects.

- Derive `Equal`, `Hash`, `Ord` on domain types instead of overriding `equals`/`hashCode`
- Use `Validation[E, A]` (not `ZIO.validate`) for pure, accumulating validation without effects
- Use `ZPure` for stateful pure programs (config evaluation, rule engines, state machines) — no fiber overhead
- Use `Associative`/`Identity` for monoïdal combination of domain values (stats, metrics aggregation)
- Never introduce Cats as a dependency solely for `Validated` or `Functor` — ZIO Prelude covers these

## Error Model — Cause and Exit

- `Exit[E, A]` is the full outcome: `Succeed(a)` or `Failure(Cause[E])`
- `Cause[E]` distinguishes: `Fail(E)` (typed), `Die(Throwable)` (defect), `Interrupt` — never conflate them
- Use `foldCauseZIO` instead of pattern-matching on `Exit` — it handles `Both`/`Then` parallel causes
- Use `sandbox`/`unsandbox` to promote defects into the typed error channel at service boundaries
- Use `unrefine` to bring specific `Throwable` defects back to typed errors; never use `catchAll(Throwable)`
- Inspect `Cause` only at the outermost layer (HTTP handler, `main`)

## Retry and Scheduling

- Never implement retry with manual recursion — use `Schedule`
- Default retry policy: `Schedule.exponential(100.millis).jittered && Schedule.recurs(n)`
- Compose schedules with `&&` (both must allow), `||` (either allows), `>>>` (sequential phases)
- Use `retryOrElse` to provide a fallback when retries are exhausted
- `ZIO.repeat(effect)(schedule)` for periodic/background tasks

## Advanced FP Patterns

### Typeclasses

- Define typeclasses as traits with a single type parameter: `trait Show[A]`
- Provide instances via `given` in companion objects for automatic derivation
- Use `summon[TC[A]]` or `using` parameters — never `implicitly`
- Prefer `derives` clause for mechanical instances (e.g., `Codec`, `Schema`)

### Higher-Kinded Types & Tagless Final

- Use tagless final (`F[_]: Monad`) for genuinely polymorphic abstractions (e.g., shared library code)
- In application code, prefer concrete ZIO types over tagless final — ZIO's ecosystem is rich enough
- When using HKT, constrain with the least powerful typeclass: `Functor` < `Applicative` < `Monad`

### Monad Transformers vs ZIO

- Avoid monad transformers (`EitherT`, `OptionT`) — use ZIO's native error channel and `Option` combinators instead
- `ZIO[R, None.type, A]` or `ZIO[R, E, Option[A]]` over `OptionT[Task, A]`

### Algebraic Design

- Model domains as ADTs: use `enum` for sum types, `case class` for product types
- Prefer smart constructors that return `Either[ValidationError, A]` or `IO[ValidationError, A]`
- Use `opaque type` for refined primitives (e.g., `NonEmptyString`, `PosInt`) — enforce invariants at construction
- Phantom types for state tracking when applicable (e.g., `Connection[Open]`, `Connection[Closed]`)

### Composition Patterns

- Prefer `flatMap`/for-comprehension for sequential, dependent effects
- Use `ZIO.collectAllPar` / `zipPar` for independent parallel effects
- Use `ZStream` / `ZPipeline` / `ZSink` for streaming data — don't accumulate in memory
- Prefer `ZIO.foldZIO` over pattern-matching on `Exit` for error recovery
- Use `Ref`, `Queue`, `Hub` for concurrent state — never `var` or mutable collections

### Functional Error Handling

- Use `ZIO.absolve` to convert `ZIO[R, E, Either[E, A]]` back to `ZIO[R, E, A]`
- Use `tapError` / `tapDefect` for side-effectful error observation without swallowing
- Compose error channels: `mapError` to translate between bounded contexts
- Use `ZIO.validate` / `ZIO.validatePar` for accumulating errors instead of fail-fast

### Type-Level Programming

- Use match types for compile-time type computation where it simplifies APIs
- Use context functions (`using` parameters) for capabilities pattern
- Avoid overusing type-level tricks — readability trumps type-safety gymnastics

## Style & Formatting

- 2-space indentation
- Use `scalafmt` with Scala 3 dialect
- Compile with `-Xfatal-warnings` — no warnings in CI
- Prefer `NonEmptyChunk` / `NonEmptyList` over bare collections when emptiness is invalid

## Build Workflow

Always run in this order before declaring work complete:

```sh
sbt compile
sbt scalafmtCheckAll
sbt test
```
