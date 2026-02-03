import datetime

class SportsSchedules:
    @staticmethod
    def get_motors_gp():
        # Hardcoded 2024/2025 GP examples - can be expanded
        today = datetime.date.today()
        gps = [
            {"name": "GP Bahrain", "date": datetime.date(2025, 3, 2), "sport": "F1"},
            {"name": "GP Saudi Arabia", "date": datetime.date(2025, 3, 9), "sport": "F1"},
            {"name": "GP Australia", "date": datetime.date(2025, 3, 23), "sport": "F1"},
            {"name": "GP Qatar", "date": datetime.date(2025, 3, 2), "sport": "MotoGP"},
            {"name": "GP Portugal", "date": datetime.date(2025, 3, 23), "sport": "MotoGP"},
            {"name": "Australian Open", "date": today, "sport": "Tennis"},
        ]
        return [gp for gp in gps if gp["date"] >= today]

    @staticmethod
    def get_channel_mapping(sport):
        mapping = {
            "F1": ["Sky Sport F1"],
            "MotoGP": ["Sky Sport MotoGP"],
            "Tennis": ["Sky Sport Tennis", "SuperTennis", "Eurosport 1", "Eurosport 2"],
            "Volleyball": ["Sky Sport Arena", "Rai Sport"]
        }
        return mapping.get(sport, [])

    @staticmethod
    def get_sport_icons():
        return {
            "F1": "https://img.icons8.com/color/48/f1.png",
            "MotoGP": "https://img.icons8.com/color/48/motorcycle.png",
            "Tennis": "https://img.icons8.com/color/48/tennis.png",
            "Volleyball": "https://img.icons8.com/color/48/volleyball.png"
        }
