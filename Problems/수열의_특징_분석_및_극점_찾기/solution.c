/*
수열의 특징 분석 및 극점 찾기

문제 설명:
정수 수열이 주어졌을 때, 해당 수열의 다양한 통계적 특징과 구조적 특징을 분석하는 프로그램을 작성해야 합니다.

요구사항:
1.  **양수, 음수, 0의 개수:** 수열 내에서 양수, 음수, 그리고 0의 개수를 각각 세어 출력합니다.
2.  **최대 연속 부분 수열의 합:** 수열 내의 연속된 부분 수열(sub-array) 중 그 합이 가장 큰 값을 찾아 출력합니다. (예: `[4, -1, 2, 1]`의 합은 6).
3.  **극점(Peak/Valley) 개수:** 수열 내의 '봉우리(Peak)'와 '골짜기(Valley)'의 개수를 각각 찾아 출력합니다.
    *   **봉우리 (Peak):** `arr[i-1] < arr[i]` 이고 `arr[i] > arr[i+1]` 인 경우의 `arr[i]` (즉, 양쪽 이웃보다 큰 값).
    *   **골짜기 (Valley):** `arr[i-1] > arr[i]` 이고 `arr[i] < arr[i+1]` 인 경우의 `arr[i]` (즉, 양쪽 이웃보다 작은 값).
    *   수열의 첫 번째와 마지막 요소는 극점(봉우리 또는 골짜기)이 될 수 없습니다.

입력 설명:
첫 번째 줄에는 수열의 길이 $N$ ($1 \le N \le 1000$)이 주어집니다.
두 번째 줄에는 공백으로 구분된 $N$개의 정수($-1000 \le \text{각 정수} \le 1000$)가 주어집니다.

출력 설명:
총 6줄에 걸쳐 다음 정보를 출력합니다.
1.  양수의 개수
2.  음수의 개수
3.  0의 개수
4.  최대 연속 부분 수열의 합
5.  봉우리의 개수
6.  골짜기의 개수

입력 예시:
7
-2 1 -3 4 -1 2 1

출력 예시:
5
2
0
6
3
2

힌트:
없음
*/

#include <stdio.h>
#include <limits.h>

#ifndef MAX
#define MAX(a, b) ((a) > (b) ? (a) : (b))
#endif

int main() {
    int N;
    scanf("%d", &N);

    int arr[N]; // C99 가변 길이 배열 (VLA)
    for (int i = 0; i < N; i++) {
        scanf("%d", &arr[i]);
    }

    // 1. 양수, 음수, 0의 개수
    int positive_count = 0;
    int negative_count = 0;
    int zero_count = 0;

    // 2. 최대 연속 부분 수열의 합 (Kadane's Algorithm)
    int max_so_far = INT_MIN;
    int current_max = 0;

    if (N > 0) {
        // Kadane's algorithm 및 초기 요소 카운트를 위한 초기화
        max_so_far = arr[0];
        current_max = arr[0];

        // arr[0]에 대한 양수/음수/0 카운트
        if (arr[0] > 0) {
            positive_count++;
        } else if (arr[0] < 0) {
            negative_count++;
        } else {
            zero_count++;
        }

        for (int i = 1; i < N; i++) {
            // 양수/음수/0 카운트
            if (arr[i] > 0) {
                positive_count++;
            } else if (arr[i] < 0) {
                negative_count++;
            } else {
                zero_count++;
            }

            // Kadane's algorithm
            current_max = MAX(arr[i], current_max + arr[i]);
            max_so_far = MAX(max_so_far, current_max);
        }
    } else { // N=0인 경우 (제약조건에 의해 N >= 1이지만, 방어적으로 처리)
        max_so_far = 0; 
    }

    // 3. 극점 (Peak/Valley) 개수
    int peak_count = 0;
    int valley_count = 0;

    if (N >= 3) { // 극점은 최소 3개 이상의 요소가 있을 때만 존재 가능
        for (int i = 1; i < N - 1; i++) {
            // Peak 조건
            if (arr[i] > arr[i-1] && arr[i] > arr[i+1]) {
                peak_count++;
            }
            // Valley 조건
            else if (arr[i] < arr[i-1] && arr[i] < arr[i+1]) {
                valley_count++;
            }
        }
    }

    printf("%d\n", positive_count);
    printf("%d\n", negative_count);
    printf("%d\n", zero_count);
    printf("%d\n", max_so_far);
    printf("%d\n", peak_count);
    printf("%d\n", valley_count);

    return 0;
}