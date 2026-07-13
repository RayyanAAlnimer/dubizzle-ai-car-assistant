import re
import pandas as pd


class InventoryService:

    def __init__(self, inventory_file):
        # Read the cleaned worksheet from the Excel file.
        self.df = pd.read_excel(
            inventory_file,
            sheet_name="cleaned dataset",
        )

        # Combine the title and desc. into one searchable column
        self.df["searchable_text"] = (
            self.df["title"].fillna("")
            + " "
            + self.df["description"].fillna("")
        ).str.lower()

        # Extract clearly-labelled cash prices
        self.df["cash_price"] = self.df["searchable_text"].apply(
            self.extract_cash_price
        )

    def get_all_cars(self):
        # Return the whole inventory
        return self.df
    
    def search(
            self, 
            make=None, 
            model=None,
            min_year=None,
            max_year=None,
            max_cash_price=None,
            keywords=None
        ):
        # Start with the complete inventory 
        results = self.df

        # Filter by make only if provided by user
        if make:
           results = results[
               results["make"].str.lower() == make.lower()
           ]

        # Filter by model only if provided by user
        if model:
           results = results[
               results["model"].str.lower() == model.lower()
           ]

        # Filter by minimum year
        if min_year:
            results = results[
                results["year"] >= min_year
            ]

        # Filter by maximum year
        if max_year:
            results = results[
                results["year"] <= max_year
            ]

        # Filter by max. cash price
        if max_cash_price:
            results = results[
                results["cash_price"].notna() 
                & (results["cash_price"] <= max_cash_price)
            ]

        # Search for keywords in the title and description
        if keywords:
            for keyword in keywords:
                results = results[
                    results["searchable_text"].str.contains(
                        keyword.lower(), 
                        regex=False
                    )
                ]

        # Return the filtered results
        return results
    
    def extract_cash_price(self, text):
        # Return no price if the listing text is empty
        if pd.isna(text):
            return None
        
        # Convert the value to a normal string
        text = str(text)

        # Look for phrases like "cash price" or "price" followed by an amount
        patterns = [
            r"cash price[:\s]*aed\s*([\d,]+)",
            r"cash price[:\s]*([\d,]+)\s*aed",
            r"aed\s*([\d,]+)\s*(?:cash|full price)",
        ]

        # Check each pattern until one matches
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)

            if match:
                # Remove commas before converting the price to an int
                price = match.group(1).replace(",", "")
                return int(price)
            
        # Return none when no clear cash price was found
        return None
