import sys
from tqdm import tqdm
from underthesea import word_tokenize


def main(input_path, output_path):

    input_file = open(input_path, encoding='utf-8')
    output_file = open(output_path, 'w', encoding='utf-8')
    for line in input_file:
        line = line.strip()
        line_tokenized = word_tokenize(line, format="text")
        output_file.write(line_tokenized+'\n')

    input_file.close()
    output_file.close()


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
