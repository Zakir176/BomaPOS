You are working on BomaPOS, a multi-tenant POS + mobile money platform for
small businesses in Zambia. Stack: FastAPI, SQLAlchemy 2.x, PostgreSQL
(Supabase), Alembic, Vue 3 PWA.

Rules for every task:
- Make the smallest change that satisfies the task. No unrelated refactors,
  renames, or formatting sweeps.
- Never trust client input for identity: tenant_id and user_id come from the
  verified auth token, never the request body.
- Money is stored as integer ngwee. Never use floats for money.
- All timestamps are timezone-aware UTC in the database.
- Every new behavior needs a pytest test. Run the full test suite before
  finishing and report the result.
- If the task is ambiguous or conflicts with existing code, stop and ask
  instead of guessing.
- At the end, list every file you changed and anything you intentionally
  did not do.