import re
import pandas as pd


class InventoryService:

    def __init__(self, inventory_file):
        self.df = pd.read_excel(
            inventory_file,
            sheet_name="cleaned dataset",
        )

        self.df["searchable_text"] = (
            self.df["title"].fillna("")
            + " "
            + self.df["description"].fillna("")
        ).str.lower()

        self.df["cash_price"] = self.df["searchable_text"].apply(
            self.extract_cash_price
        )

    def get_all_cars(self):
        """Return the full inventory DataFrame."""
        return self.df

    def search(
        self,
        make=None,
        model=None,
        min_year=None,
        max_year=None,
        max_cash_price=None,
        keywords=None,
    ):
        """Filter the inventory using structured search fields."""
        results = self.df

        if make:
            results = results[
                results["make"].str.lower() == make.lower()
            ]

        if model:
            results = results[
                results["model"].str.lower() == model.lower()
            ]

        if min_year:
            results = results[
                results["year"] >= min_year
            ]

        if max_year:
            results = results[
                results["year"] <= max_year
            ]

        if max_cash_price:
            results = results[
                results["cash_price"].notna()
                & (results["cash_price"] <= max_cash_price)
            ]

        if keywords:
            for keyword in keywords:
                results = results[
                    results["searchable_text"].str.contains(
                        keyword.lower(),
                        regex=False,
                    )
                ]

        return results

    def extract_cash_price(self, text):
        """Extract clearly labeled cash prices from listing text."""
        if pd.isna(text):
            return None

        text = str(text)

        patterns = [
            r"cash price[:\s]*aed\s*([\d,]+)",
            r"cash price[:\s]*([\d,]+)\s*aed",
            r"aed\s*([\d,]+)\s*(?:cash|full price)",
        ]

        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)

            if match:
                price = match.group(1).replace(",", "")
                return int(price)

        return None
