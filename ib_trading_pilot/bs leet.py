def decode(message_file):
    # Initialize variables
    decoded_words = []
    current_line = 1
    next_pyramid_end = 1

    # Open and read the file line by line
    with open(message_file, 'r') as file:
        for line in file:
            # Split the line into number and word
            number, word = line.split()
            number = int(number)

            # Check if the current line is at the end of a pyramid
            if current_line == next_pyramid_end:
                decoded_words.append(word)
                # Calculate the end of the next pyramid line
                next_pyramid_end += len(decoded_words) + 1

            # Move to the next line
            current_line += 1

    # Join the words to form the decoded message
    decoded_message = ' '.join(decoded_words)
    return decoded_message

# Example usage:
# message = decode('path_to_message_file.txt')
# print(message)

a = decode(coding)

