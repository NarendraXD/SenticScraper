import argparse
import os
import re
import pandas as pd
import nltk
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from bs4 import BeautifulSoup

# ---------------- Load StopWords & MasterDictionary ---------------- #
def load_stopwords(stopwords_dir):
    stopwords = set()
    for file in os.listdir(stopwords_dir):
        if file.endswith(".txt"):
            with open(os.path.join(stopwords_dir, file), "r", encoding="latin-1") as f:
                for line in f:
                    word = line.strip()
                    if word:
                        stopwords.add(word.lower())
    return stopwords

def load_master_dictionary(dict_dir):
    positive, negative = set(), set()
    for file in os.listdir(dict_dir):
        if file.endswith(".txt"):
            path = os.path.join(dict_dir, file)
            if "positive" in file.lower():
                with open(path, "r", encoding="latin-1") as f:
                    for w in f: positive.add(w.strip().lower())
            elif "negative" in file.lower():
                with open(path, "r", encoding="latin-1") as f:
                    for w in f: negative.add(w.strip().lower())
    return positive, negative


# ---------------- Selenium Article Extraction ---------------- #
def extract_article(url, driver):
    try:
        driver.get(url)
        soup = BeautifulSoup(driver.page_source, "html.parser")

        # Try <article> first
        article = soup.find("article")
        if article:
            title = article.find("h1").get_text(strip=True) if article.find("h1") else ""
            text = " ".join([p.get_text(strip=True) for p in article.find_all("p")])
            return title, text

        # Fallback: biggest <div>
        h1 = soup.find("h1")
        title = h1.get_text(strip=True) if h1 else ""
        divs = soup.find_all("div")
        best = max(divs, key=lambda d: len(d.get_text(strip=True)), default=None)
        text = best.get_text(" ", strip=True) if best else ""
        return title, text
    except Exception as e:
        print(f"⚠️ Error scraping {url}: {e}")
        return "", ""


# ---------------- Text Analysis ---------------- #
def clean_and_tokenize(text, stopwords):
    words = nltk.word_tokenize(text)
    words = [re.sub(r'[^A-Za-z]', '', w).lower() for w in words]
    return [w for w in words if w and w not in stopwords]

def count_syllables(word):
    word = word.lower()
    vowels = "aeiou"
    count = 0
    prev_vowel = False
    for ch in word:
        if ch in vowels:
            if not prev_vowel: count += 1
            prev_vowel = True
        else:
            prev_vowel = False
    if word.endswith(("es","ed")): count = max(1, count-1)
    return count if count > 0 else 1

def analyze_text(text, stopwords, pos_dict, neg_dict):
    sentences = nltk.sent_tokenize(text)
    cleaned_words = clean_and_tokenize(text, stopwords)

    pos_score = sum(1 for w in cleaned_words if w in pos_dict)
    neg_score = sum(1 for w in cleaned_words if w in neg_dict)
    polarity = (pos_score - neg_score) / ((pos_score + neg_score) + 0.000001)
    subjectivity = (pos_score + neg_score) / (len(cleaned_words) + 0.000001)

    word_count = len(cleaned_words)
    sent_count = max(1, len(sentences))
    avg_sentence_length = word_count / sent_count
    complex_words = [w for w in cleaned_words if count_syllables(w) > 2]
    complex_word_count = len(complex_words)
    pct_complex_words = complex_word_count / word_count if word_count else 0
    fog_index = 0.4 * (avg_sentence_length + pct_complex_words)

    syllables_per_word = sum(count_syllables(w) for w in cleaned_words) / word_count if word_count else 0
    personal_pronouns = len(re.findall(r"\\b(I|we|my|ours|us)\\b", text, re.I)) - len(re.findall(r"\\bUS\\b", text))
    avg_word_length = sum(len(w) for w in cleaned_words) / word_count if word_count else 0

    return {
        "POSITIVE SCORE": pos_score,
        "NEGATIVE SCORE": neg_score,
        "POLARITY SCORE": polarity,
        "SUBJECTIVITY SCORE": subjectivity,
        "AVG SENTENCE LENGTH": avg_sentence_length,
        "PERCENTAGE OF COMPLEX WORDS": pct_complex_words,
        "FOG INDEX": fog_index,
        "AVG NUMBER OF WORDS PER SENTENCE": avg_sentence_length,
        "COMPLEX WORD COUNT": complex_word_count,
        "WORD COUNT": word_count,
        "SYLLABLE PER WORD": syllables_per_word,
        "PERSONAL PRONOUNS": personal_pronouns,
        "AVG WORD LENGTH": avg_word_length
    }


# ---------------- Main ---------------- #
def main(input_path, output_path, articles_dir, stopwords_dir, dict_dir, output_structure_path):
    nltk.download("punkt", quiet=True)
    nltk.download("punkt_tab", quiet=True)

    stopwords = load_stopwords(stopwords_dir)
    pos_dict, neg_dict = load_master_dictionary(dict_dir)
    df = pd.read_excel(input_path, engine="openpyxl")

    os.makedirs(articles_dir, exist_ok=True)
    results = []

    # Setup Selenium ChromeDriver (headless)
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    driver = webdriver.Chrome(options=chrome_options)

    for _, row in df.iterrows():
        url_id, url = str(row["URL_ID"]), row["URL"]
        title, text = extract_article(url, driver)
        if not text: continue

        with open(os.path.join(articles_dir, f"{url_id}.txt"), "w", encoding="utf-8") as f:
            f.write(title + "\\n\\n" + text)

        analysis = analyze_text(title + " " + text, stopwords, pos_dict, neg_dict)
        out = row.to_dict()
        out.update(analysis)
        results.append(out)

    driver.quit()

    df_out = pd.DataFrame(results)
    structure_df = pd.read_excel(output_structure_path, engine="openpyxl")
    ordered_cols = list(structure_df.columns)
    df_out = df_out.reindex(columns=ordered_cols)

    df_out.to_excel(output_path, index=False, engine="openpyxl")
    print(f"✅ Output saved to {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="Input.xlsx")
    parser.add_argument("--output", default="Output.xlsx")
    parser.add_argument("--articles_dir", default="articles")
    parser.add_argument("--stopwords_dir", default="StopWords")
    parser.add_argument("--dict_dir", default="MasterDictionary")
    parser.add_argument("--output_structure", default="Output Data Structure.xlsx")
    args = parser.parse_args()
    main(args.input, args.output, args.articles_dir, args.stopwords_dir, args.dict_dir, args.output_structure)
