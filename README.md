# SLUGGER-Stats-Widget
A Streamlit app that pulls baseball statistics from the Pointstreak API and displays interactive hitter and pitcher reports with downloadable PDF summaries.

# Features:
- Team and player filtering
- Pitcher and hitter tabs
- Season stats and game logs
- Rolling “hot/cold” indicators based on recent performance
- Downloadable PDF reports
- Cached API requests for faster loading

# How to Run:
1. Clone the Repository
    git clone <repo-url>
    cd <repo-name>
2. Install Dependencies
    pip install -r requirements.txt
3. API Setup
    Create a .env file in the project root:
    API_KEY=your_api_key_here
4. Running the App
    streamlit run widget.py

After running the command, Streamlit should open automatically in your browser. If not, open the local URL shown in the terminal (usually something like http://localhost:8501).


# How It Works
The app pulls live baseball data from the Pointstreak API and processes:
- player information
- pitch data
- game data
- hitting/pitching statistics

Users can:
- select a team
- filter by player
- customize displayed stats
- export reports as PDFs

Hot/cold labels are based on rolling percentiles from a player’s last 7 games:
🔥 = top 25%
🧊 = bottom 25%

# Project Structure: 
project/
│
├── widget.py
├── .env
├── requirements.txt
└── README.md

# Future Work
The current version of the stats widget pulls data from the Pointstreak API. The future version of the project will have to transition to the iScore API, which provides additional statistics not currently available, including fielding data.

Because of this, the widget will need to expand to support fielders by:
- adding a new “Fielders” tab
- creating season-level and game-level fielding stat tables
- integrating fielding metrics into the existing filtering and PDF export systems

As for the iScore migration, the widget displays season level pitching and hitting statistics. I have been unable to work successfully with the leaderboard endpoints, which I was going to use for the hot/cold indicators and the percentile rankings. I have also been unable to work successfully with the GET Games Played by a Player to see whether the widget can display game-level statistics. 

If iScore can accurately track when multiple pitchers pitch in one game and can differentiate the pitcher's stats, then implementing the lefty/righty splits would be a good addition to the widget as well. 
