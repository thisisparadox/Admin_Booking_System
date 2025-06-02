import pymysql

# Database configuration
DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': 'admin'
}

def create_database():
    try:
        # Connect to MySQL server
        connection = pymysql.connect(**DB_CONFIG)
        cursor = connection.cursor()
        
        # Create database if it doesn't exist
        cursor.execute("CREATE DATABASE IF NOT EXISTS storm_db")
        print("Database 'storm_db' created successfully!")
        
        cursor.close()
        connection.close()
        
    except pymysql.Error as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    create_database() 