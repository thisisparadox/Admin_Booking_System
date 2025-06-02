# Storm Admin Project

A Django-based administration system for managing bookings, services, and transactions.

## Setup Instructions

1. Create a virtual environment:
```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Configure environment variables:
- Copy `.env.example` to `.env`
- Update the values in `.env` with your configuration

4. Create the database:
```bash
python create_db.py
python manage.py migrate
```

5. Create a superuser:
```bash
python manage.py createsuperuser
```

6. Run the development server:
```bash
python manage.py runserver
```

## Project Structure

- `stormadmin/` - Main project configuration
- `uiadmin/` - Main application code
- `static/` - Static files (CSS, JS, images)
- `media/` - User-uploaded files
- `staticfiles/` - Collected static files for production

## Security Notes

1. In production:
   - Set `DEBUG=False` in .env
   - Update `ALLOWED_HOSTS` in settings.py
   - Use a proper web server (e.g., Gunicorn)
   - Set a strong `SECRET_KEY`

2. Database:
   - Use strong passwords
   - Regularly backup your database
   - Consider using environment variables for sensitive data

## Features

- User Authentication
- Dashboard
- Booking Management
- Service Management
- Transaction Management
- Staff Management
- Blog System

## Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request 