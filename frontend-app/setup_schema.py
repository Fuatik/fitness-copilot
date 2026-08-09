"""Schema setup script to fix database structure."""
import lakebase

def setup_schema():
    print("Setting up database schema...")
    
    # 1. Add missing columns to user_programs table
    print("Checking user_programs table...")
    try:
        lakebase.run_query("""
            ALTER TABLE user_programs 
            ADD COLUMN IF NOT EXISTS start_date DATE DEFAULT CURRENT_DATE
        """)
        print("✓ Added start_date column to user_programs")
    except Exception as e:
        print(f"Note: {e}")
    
    # 2. Create user_test_results table if it doesn't exist
    print("Checking user_test_results table...")
    try:
        lakebase.run_query("""
            CREATE TABLE IF NOT EXISTS user_test_results (
                user_id_hash TEXT NOT NULL,
                exercise_name TEXT NOT NULL,
                one_rm DECIMAL(5, 1) NOT NULL,
                test_date DATE DEFAULT CURRENT_DATE,
                PRIMARY KEY (user_id_hash, exercise_name)
            )
        """)
        print("✓ Created user_test_results table")
    except Exception as e:
        print(f"Error creating user_test_results: {e}")
    
    # 3. Ensure current_week column exists in user_programs
    try:
        lakebase.run_query("""
            ALTER TABLE user_programs 
            ADD COLUMN IF NOT EXISTS current_week INTEGER DEFAULT 1
        """)
        print("✓ Ensured current_week column exists in user_programs")
    except Exception as e:
        print(f"Note: {e}")
    
    print("\n✅ Schema setup complete!")

if __name__ == "__main__":
    setup_schema()