import streamlit as st
import openai
import requests
import time
from datetime import datetime, timedelta
import json
import yfinance as yf
import plotly.graph_objects as go
# Set your API keys in Streamlit secrets or environment variables
openai.api_key = st.secrets["OPENAI_API_KEY"]
FMP_API_KEY = st.secrets["FMP_API_KEY"]

current_year = datetime.now().year
SYSTEM_INSTRUCTIONS = f"""
You are an experienced investment analyst with years of experience in analyzing earnings call transcripts. Your task is to:
1. Extract the speakers and their positions from the earnings call transcript.
2. Summarize the key points discussed in the call.
3. Provide an opinion on the prospects for the company based on the call .
4. Be aware of and adjust for the inherent positive bias often present in these transcripts.
5. Highlight any potential red flags or areas of concern, even if they're subtly mentioned.
6. Provide a balanced view, considering both positive and negative aspects discussed.
7. Summarised the questions asked

Your analysis should be insightful, critical, and unbiased. Don't hesitate to point out inconsistencies or vague statements in the transcript.


"""

def extract_year_and_ticker(user_input):
    tools = [
        {
            "type": "function",
            "function": {
            "name": "extract_info",
            "description": "Extract the year and ticker/company name from the user input",
            "parameters": {
                "type": "object",
                "properties": {
                    "year": {
                        "type": "integer",
                        "description": "The year mentioned in the input, or the current year if not specified",
                    },
                    "ticker_or_company": {
                        "type": "string",
                        "description": "The stock ticker or company name mentioned in the input",
                    },
                },
                "required": ["year", "ticker_or_company"],
            },
        }
        }
    ]

    response = openai.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "system", "content": """ as an experienced investment analyst, extract the ticker of the company and year mentioned from the input,
                    if the company name is mentioned then use your knowledge as the analyst to out putthe ticker in the json response, 
                   return the latest year, which is 2024 if no specific time frame is given. for example 'latest microsoft earnings call', the expected json output should be:
                    {"ticker":"MSFT", "year":2024}"}"""},

                {"role": "user", "content": user_input}],
        tools=tools
    )

    function_response = response.choices[0].message.tool_calls[0]
    print(function_response)
    arguments = json.loads(function_response.function.arguments)

    extracted_info = {}
    extracted_info['year'] = arguments.get('year')
    extracted_info['ticker_or_company'] = arguments.get('ticker_or_company')
    #extracted_info = eval(arguments)
    

    if extracted_info['year'] == datetime.now().year:
        st.info("Year not specified, using current year.")

    return extracted_info['year'], extracted_info['ticker_or_company']

def convert_company_to_ticker(company_name):
    url = f"https://financialmodelingprep.com/api/v3/search?query={company_name}&limit=1&apikey={FMP_API_KEY}"
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        if data:
            return data[0]['symbol']
    return None

def get_transcripts(single_ticker, transcript_year, max_retries=5, year_retries=3):
    headers = {
        "User-Agent": "Mozilla/5.0"
    }
    for _ in range(year_retries):
        transcripts_url = f"https://financialmodelingprep.com/api/v4/batch_earning_call_transcript/{single_ticker}?&year={transcript_year}&apikey={FMP_API_KEY}"
        for attempt in range(max_retries):
            try:
                response = requests.get(transcripts_url, headers=headers)
                if response.status_code == 200:
                    transcripts = response.json()
                    if isinstance(transcripts, list) and transcripts:
                        return transcripts[0]
                    else:
                        st.warning(f"No transcripts found for {transcript_year}. Reducing year by 1 and retrying...")
                        break
                elif response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", 5))
                    st.warning(f"Rate limit exceeded. Retrying after {retry_after} seconds... (Attempt {attempt + 1}/{max_retries})")
                    time.sleep(retry_after)
                else:
                    response.raise_for_status()
            except requests.exceptions.RequestException as e:
                st.error(f"Request failed: {e}")
                if attempt + 1 == max_retries:
                    return None
                time.sleep(2 ** attempt)
        transcript_year -= 1
    st.error("Max retries for year reduction exceeded. No data found.")
    return None

def analyze_transcript(transcript):
    messages = [
        {"role": "system", "content": SYSTEM_INSTRUCTIONS},
        {"role": "user", "content": f"Please analyze this earnings call transcript and provide your insights:\n\n{transcript['content']}"}
    ]
    
    response = openai.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        temperature=0.2,
        max_tokens=2000
    )
    
    return response.choices[0].message.content

def process_user_input(user_input):
    year, ticker_or_company = extract_year_and_ticker(user_input)
    ticker = convert_company_to_ticker(ticker_or_company) or ticker_or_company
    transcript = get_transcripts(ticker, year)
    if transcript:
        analysis = analyze_transcript(transcript)
        return transcript, analysis
    return None, None

def generate_price_chart(ticker, earnings_date, year):
    # Convert earnings_date string to datetime object, handling the time component
    try:
        earnings_date = datetime.strptime(earnings_date, "%Y-%m-%d %H:%M:%S")
        print(earnings_date)
    except ValueError:
        # If the above fails, try without the time component
        earnings_date = datetime.strptime(earnings_date, "%Y-%m-%d")
    
    # Set the start date to 30 days before the earnings call
    start_date = earnings_date - timedelta(days=30)
    
    # Set the end date to 30 days after the earnings call or today, whichever is earlier
    end_date = min(earnings_date + timedelta(days=30), datetime.now())
    
    # Fetch stock data
    stock_data = yf.download(ticker, start=start_date, end=end_date)
    
    # Create the price chart
    fig = go.Figure()
    
    # Add closing price line
    fig.add_trace(go.Scatter(
        x=stock_data.index,
        y=stock_data['Close'],
        mode='lines',
        name='Close Price',
        line=dict(color='#1f77b4', width=2)
    ))
    
    # Add earnings call vertical line as a shape
    fig.add_shape(
        type="line",
        x0=earnings_date,
        y0=0,
        x1=earnings_date,
        y1=1,
        yref="paper",
        line=dict(color="red", width=2, dash="dash"),
    )
    
    # Add annotation for the earnings call
    fig.add_annotation(
        x=earnings_date,
        y=1,
        yref="paper",
        text="Earnings Call",
        showarrow=False,
        yshift=10
    )
    
    # Customize the layout
    fig.update_layout(
        title=f"{ticker} Stock Price",
        xaxis_title="Date",
        yaxis_title="Price (USD)",
        template="plotly_white",
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    
    # Set axis ranges manually
    fig.update_xaxes(range=[start_date, end_date])
    fig.update_yaxes(range=[stock_data['Close'].min() * 0.95, stock_data['Close'].max() * 1.05])
    
    return fig

def main():
    st.title("AI Earnings Call Analyst")
    st.write("Ask about any company's latest earnings call. Our AI will analyze it and provide insights.")

    user_input = st.text_input("What earnings call transcript would you like analyzed?", 
                               placeholder="E.g., 'Analyze Apple's latest earnings call'")

    if user_input:
        with st.spinner("Fetching and analyzing transcript..."):
            transcript, analysis = process_user_input(user_input)

        if transcript and analysis:
            st.subheader(f"Transcript Analysis for {transcript['symbol']} - {transcript['date']}")
            
            st.markdown("### AI Analysis")
            # Generate and display the price chart
            chart = generate_price_chart(transcript['symbol'], transcript['date'], transcript['year'])
            st.plotly_chart(chart, use_container_width=True)
            st.write(analysis)
            
            
            
            with st.expander("View Full Transcript"):
                st.write(transcript['content'])
        else:
            st.error("Unable to fetch or analyze the transcript. Please try a different query.")

if __name__ == "__main__":
    main()
