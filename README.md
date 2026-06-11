# NutriLog 🥗

A mobile-friendly food intake tracker with a full admin panel.

## Quick Start

```bash
# Install Flask (if not already installed)
pip install flask

# Run the app
python start.py
```

Then open:
- **Food Log**: http://localhost:5000
- **Admin Panel**: http://localhost:5000/admin

## Features

### Mobile App (`/`)
- Daily food log with 7 meal slots: Breakfast, Morning Tea, Lunch, Afternoon Tea, Dinner, Drinks, Snacks
- Tap any slot to expand and add food items
- Search across all foods by name or category
- Quantity selector (0.5 increments) with live calorie preview
- Daily macro totals (calories, protein, carbs, fat)
- Navigate between dates with prev/next arrows

### Admin Panel (`/admin`)
- Manage categories (add, edit, delete, reorder, custom emoji icons)
- Manage food items per category (add, edit, delete)
- Each item stores: name, serving size, serving unit, calories, protein, carbs, fat, notes
- Pre-loaded with 35+ common Australian food items across all default categories

## Database

SQLite database (`nutrilog.db`) with three tables:

### `categories`
| Column | Type | Description |
|--------|------|-------------|
| id | TEXT | UUID primary key |
| name | TEXT | Category name |
| icon | TEXT | Emoji icon |
| sort_order | INTEGER | Display order |
| created_at | TEXT | ISO timestamp |

### `food_items`
| Column | Type | Description |
|--------|------|-------------|
| id | TEXT | UUID primary key |
| category_id | TEXT | FK → categories |
| name | TEXT | Food name |
| serving_size | TEXT | Recommended serving amount |
| serving_unit | TEXT | g / ml / cup / piece etc. |
| calories | INTEGER | kcal per serving |
| protein_g | REAL | Grams of protein |
| carbs_g | REAL | Grams of carbohydrates |
| fat_g | REAL | Grams of fat |
| notes | TEXT | Optional notes |
| created_at | TEXT | ISO timestamp |

### `food_log`
| Column | Type | Description |
|--------|------|-------------|
| id | TEXT | UUID primary key |
| food_item_id | TEXT | FK → food_items |
| meal_slot | TEXT | Category ID (meal slot) |
| log_date | TEXT | ISO date (YYYY-MM-DD) |
| quantity | REAL | Multiplier (1.0 = 1 serving) |
| calories_actual | INTEGER | Computed calories |
| logged_at | TEXT | ISO timestamp |
| notes | TEXT | Optional entry notes |

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/categories` | List all categories |
| POST | `/api/categories` | Create category |
| PUT | `/api/categories/:id` | Update category |
| DELETE | `/api/categories/:id` | Delete category |
| GET | `/api/food-items` | List all food items |
| GET | `/api/food-items?category_id=X` | Filter by category |
| POST | `/api/food-items` | Create food item |
| PUT | `/api/food-items/:id` | Update food item |
| DELETE | `/api/food-items/:id` | Delete food item |
| GET | `/api/log?date=YYYY-MM-DD` | Get daily log |
| POST | `/api/log` | Add log entry |
| DELETE | `/api/log/:id` | Remove log entry |
| GET | `/api/log/summary?date=X` | Daily calorie/macro summary |
| GET | `/api/log/history?days=7` | Recent daily totals |
| GET | `/api/export` | Full data export (for AI) |

## AI Export

`GET /api/export` returns the complete database as JSON — categories, food items, and full log history — ready for AI analysis, meal planning, or pattern recognition.

## Deployment (Production)

For a persistent server (e.g. Windows Server IIS or Linux):

```bash
pip install gunicorn
gunicorn -w 2 -b 0.0.0.0:5000 app:app
```

Or use a Windows Service wrapper like NSSM to run `python start.py` as a background service.
