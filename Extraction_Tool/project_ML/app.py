import streamlit as st
import pandas as pd
import pickle
from sklearn.preprocessing import StandardScaler

# ---------------------------------
# Streamlit Page Configuration
# ---------------------------------
st.set_page_config(page_title="Rugby Match Predictor", layout="centered")

st.title("Premiership Rugby 2025 — Match Predictor")
st.markdown("Predict the winner using **Decision Tree**, **Random Forest**, and **SVC** models.")

# ---------------------------------
# Step 1: Load Data & Models
# ---------------------------------
@st.cache_resource
def load_models():
    with open("DecisionTree_model.pkl", "rb") as f:
        dt_model = pickle.load(f)
    with open("RandomForest_model.pkl", "rb") as f:
        rf_model = pickle.load(f)
    with open("SVC_model.pkl", "rb") as f:
        svc_model = pickle.load(f)
    with open("scaler.pkl", "rb") as f:
        scaler = pickle.load(f)
    df = pd.read_csv("rugby_data.csv")
    return df, dt_model, rf_model, svc_model, scaler

try:
    df, dt_model, rf_model, svc_model, scaler = load_models()
    st.success("Models and data loaded successfully!")
except Exception as e:
    st.error(f"Failed to load model/data. Please run `train_model.py` first.\n\nError: {e}")
    st.stop()

# ---------------------------------
# Step 2: Show Dataset
# ---------------------------------
with st.expander("View Dataset"):
    st.dataframe(df.head())

teams = sorted(set(df["Team_A"]).union(df["Team_B"]))

# ---------------------------------
# Step 3: Match Prediction UI
# ---------------------------------
st.header(" Predict a Match Result")

col1, col2 = st.columns(2)
team_a = col1.selectbox(" Home Team", teams)
team_b = col2.selectbox(" Away Team", teams)

if team_a == team_b:
    st.warning(" Please select two different teams.")
    st.stop()

# ---------------------------------
# Step 4: Feature Engineering
# ---------------------------------
team_matches = df[((df["Team_A"] == team_a) & (df["Team_B"] == team_b)) |
                  ((df["Team_A"] == team_b) & (df["Team_B"] == team_a))]

if team_matches.empty:
    team_a_avg = df[df["Team_A"] == team_a]["Score_diff"].mean()
    team_b_avg = df[df["Team_A"] == team_b]["Score_diff"].mean()
    avg_diff = 0 if pd.isna(team_a_avg) or pd.isna(team_b_avg) else (team_a_avg - team_b_avg) / 2
    note = "No direct match data — using average team performance."
else:
    team_a_diff = team_matches.loc[team_matches["Team_A"] == team_a, "Score_diff"].mean()
    team_b_diff = -(team_matches.loc[team_matches["Team_A"] == team_b, "Score_diff"]).mean()
    avg_diff = (team_a_diff if pd.notna(team_a_diff) else 0) + (team_b_diff if pd.notna(team_b_diff) else 0)
    note = "Prediction based on past head-to-head data."

X_sample = pd.DataFrame({"Score_diff": [avg_diff]})
X_scaled = scaler.transform(X_sample)

# ---------------------------------
# Step 5: Predictions
# ---------------------------------
models = {
    "Decision Tree": dt_model,
    "Random Forest": rf_model,
    "SVC": svc_model
}

predictions = {}
for name, model in models.items():
    pred = model.predict(X_scaled)[0]
    winner = team_a if pred == 1 else team_b
    predictions[name] = winner

# ---------------------------------
# Step 6: Display Results (No Chart)
# ---------------------------------
st.subheader("Predicted Winners:")
for name, winner in predictions.items():
    st.write(f"**{name}** → {winner}")

st.info(f"Note: {note}")

st.markdown("---")
st.caption("Developed by Dinesh | Rugby Match Winner Predictor")
