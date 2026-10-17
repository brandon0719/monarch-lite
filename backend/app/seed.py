"""Default categories and keyword rules (FR-CAT-03). Applied by the initial migration."""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Category, Rule

# (name, group_name, bucket)
CATEGORIES = [
    ("Rent", "Housing", "needs"),  # classic 50/30/20: rent counts in Needs
    ("Utilities", "Housing", "needs"),
    ("Groceries", "Essentials", "needs"),
    ("Transportation", "Essentials", "needs"),
    ("Healthcare", "Essentials", "needs"),
    ("Insurance", "Essentials", "needs"),
    ("Debt Payments", "Essentials", "needs"),
    ("Dining", "Lifestyle", "needs"),  # the owner counted dining as a need in the old tracker
    ("Entertainment", "Lifestyle", "wants"),
    ("Shopping", "Lifestyle", "wants"),
    ("Subscriptions", "Lifestyle", "wants"),
    ("Travel", "Lifestyle", "wants"),
    ("Savings Transfer", "Savings", "savings"),
    ("Investment Contribution", "Savings", "savings"),
    ("Paycheck", "Income", "income"),
    ("Other Income", "Income", "income"),
    ("Transfer", "Transfers", "excluded"),
    ("Credit Card Payment", "Transfers", "excluded"),
]

# (substring, category). List order is priority: first match wins.
KEYWORD_RULES = [
    ("payroll", "Paycheck"),  # first, so Amazon paychecks never hit "amazon" -> Shopping
    ("trader joe", "Groceries"), ("whole foods", "Groceries"), ("safeway", "Groceries"),
    ("kroger", "Groceries"), ("costco", "Groceries"),
    ("doordash", "Dining"), ("uber eats", "Dining"), ("grubhub", "Dining"),
    ("starbucks", "Dining"), ("chipotle", "Dining"), ("mcdonald", "Dining"),
    ("uber", "Transportation"), ("lyft", "Transportation"), ("shell", "Transportation"),
    ("chevron", "Transportation"), ("exxon", "Transportation"), ("transit", "Transportation"),
    ("pg&e", "Utilities"), ("pge", "Utilities"), ("comcast", "Utilities"), ("xfinity", "Utilities"),
    ("verizon", "Utilities"), ("at&t", "Utilities"), ("water dept", "Utilities"),
    ("netflix", "Subscriptions"), ("spotify", "Subscriptions"), ("hulu", "Subscriptions"),
    ("disney+", "Subscriptions"), ("patreon", "Subscriptions"),
    ("amazon", "Shopping"), ("target", "Shopping"), ("walmart", "Shopping"),
    ("cvs", "Healthcare"), ("walgreens", "Healthcare"), ("pharmacy", "Healthcare"),
    ("geico", "Insurance"), ("state farm", "Insurance"),
    ("landlord", "Rent"),
    ("zelle", "Transfer"), ("venmo", "Transfer"), ("apple cash", "Transfer"), ("interest payment", "Transfer"),
    # Card payments before the generic "autopay": "CHASE CREDIT CRD AUTOPAY" contains both.
    ("credit crd", "Credit Card Payment"), ("gsbank payment", "Credit Card Payment"),
    ("e-payment", "Credit Card Payment"), ("payment to chase card", "Credit Card Payment"),
    ("autopay", "Transfer"),
    ("deposit", "Transfer"), ("banklink", "Transfer"), ("ach pull", "Transfer"),
    ("expedia", "Travel"), ("airbnb", "Travel"), ("hotel", "Travel"),
    ("airlines", "Travel"), ("marriott", "Travel"), ("hilton", "Travel"),
    ("mta", "Transportation"), ("lirr", "Transportation"), ("metro", "Transportation"),
    ("cafe", "Dining"), ("coffee", "Dining"), ("taco", "Dining"), ("pizza", "Dining"),
    ("sushi", "Dining"), ("diner", "Dining"), ("restaurant", "Dining"),
]


def seed_defaults(db: Session) -> None:
    """Insert defaults on an empty database; a no-op otherwise."""
    if db.scalar(select(func.count(Category.id))):
        return
    categories = {name: Category(name=name, group_name=group, bucket=bucket) for name, group, bucket in CATEGORIES}
    db.add_all(categories.values())
    db.flush()
    db.add_all(
        Rule(priority=i, contains_text=keyword, set_category_id=categories[name].id)
        for i, (keyword, name) in enumerate(KEYWORD_RULES)
    )
    db.commit()
